"""Detector auto-tuning driver.

Usage:
    python scripts/tune_detector.py --trials 200 --output artifacts/tuning/run_001

Outputs, under <output>/:
    baseline.json        -- default config scores on full manifest
    study.db             -- Optuna storage (resumable)
    best_config.json     -- winning DetectorConfig
    train_scores.json    -- tuned config on train split
    holdout_scores.json  -- tuned config on holdout split (the overfit check)
    report.md            -- human-readable summary
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import optuna

from stl2scad.core.converter import get_openscad_path, run_openscad
from stl2scad.core.feature_fixtures import (
    load_feature_fixture_manifest,
    write_feature_fixture_library,
)
from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import ManifestScore, score_manifest
from stl2scad.tuning.search_space import suggest_config
from stl2scad.tuning.splits import leave_one_out, stratified_split

logger = logging.getLogger(__name__)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="tests/data/feature_fixtures_manifest.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--holdout-ratio", type=float, default=0.25)
    parser.add_argument("--cross-validate", action="store_true")
    args = parser.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = load_feature_fixture_manifest(Path(args.manifest))

    stl_dir = args.output / "fixtures"
    stl_dir.mkdir(exist_ok=True)
    _render_fixtures(Path(args.manifest), fixtures, stl_dir)

    train, holdout = stratified_split(fixtures, holdout_ratio=args.holdout_ratio, seed=args.seed)
    logger.info("Train: %d fixtures, Holdout: %d fixtures", len(train), len(holdout))
    baseline_train = score_manifest(DetectorConfig(), train, stl_dir)
    baseline_holdout = score_manifest(DetectorConfig(), holdout, stl_dir) if holdout else None

    if not args.cross_validate:
        baseline_full = score_manifest(DetectorConfig(), fixtures, stl_dir)
        _dump(args.output / "baseline.json", _serialize_score(baseline_full, fixtures))
        logger.info("Baseline (full manifest) mean: %.4f", baseline_full.mean)

        storage = f"sqlite:///{(args.output / 'study.db').as_posix()}"
        study = optuna.create_study(
            study_name="detector_autotune",
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=args.seed),
            storage=storage,
            load_if_exists=True,
        )

        def objective(trial: optuna.Trial) -> float:
            config = suggest_config(trial)
            return score_manifest(config, train, stl_dir).mean

        study.optimize(objective, n_trials=args.trials, show_progress_bar=True)
        logger.info("Best train score: %.4f", study.best_value)

        best_config = _reconstruct_config(study.best_params)
        tuned_train = score_manifest(best_config, train, stl_dir)
        tuned_holdout = score_manifest(best_config, holdout, stl_dir) if holdout else None
        selected_config_source = "optuna_best"

        # Guardrail: never recommend a regressive config when search misses baseline.
        if tuned_train.mean < baseline_train.mean:
            logger.info(
                "Best sampled config underperformed baseline on train (%.4f < %.4f); "
                "falling back to DetectorConfig defaults.",
                tuned_train.mean,
                baseline_train.mean,
            )
            best_config = DetectorConfig()
            tuned_train = baseline_train
            tuned_holdout = baseline_holdout if holdout else None
            selected_config_source = "baseline_fallback"

        _dump(args.output / "best_config.json", dataclasses.asdict(best_config))
        _dump(args.output / "train_scores.json", _serialize_score(tuned_train, train))
        if tuned_holdout is not None:
            _dump(args.output / "holdout_scores.json", _serialize_score(tuned_holdout, holdout))

        _write_report(
            args.output / "report.md",
            args=args,
            baseline_full=baseline_full,
            baseline_train=baseline_train,
            baseline_holdout=baseline_holdout,
            tuned_train=tuned_train,
            tuned_holdout=tuned_holdout,
            fixtures=fixtures,
            train=train,
            holdout=holdout,
            selected_config_source=selected_config_source,
        )

    if args.cross_validate:
        fold_scores: list[float] = []
        fold_params: list[dict] = []
        for fold_index, (fold_train, fold_holdout) in enumerate(leave_one_out(fixtures)):
            study = optuna.create_study(
                study_name=f"cv_fold_{fold_index}",
                direction="maximize",
                sampler=optuna.samplers.TPESampler(seed=args.seed + fold_index),
            )
            study.optimize(
                lambda trial: score_manifest(suggest_config(trial), fold_train, stl_dir).mean,
                n_trials=max(10, args.trials // len(fixtures)),
                show_progress_bar=False,
            )
            fold_config = _reconstruct_config(study.best_params)
            fold_holdout_score = score_manifest(fold_config, fold_holdout, stl_dir).mean
            fold_scores.append(fold_holdout_score)
            fold_params.append(study.best_params)
            logger.info("Fold %d/%d: holdout=%.4f", fold_index + 1, len(fixtures), fold_holdout_score)
        _write_cv_report(args.output / "cv_report.md", fold_scores, fold_params, fixtures)

    return 0


def _reconstruct_config(params: dict) -> DetectorConfig:
    defaults = DetectorConfig()
    fields = {f.name for f in dataclasses.fields(defaults)}
    filtered = {k: v for k, v in params.items() if k in fields}
    return dataclasses.replace(defaults, **filtered)


def _render_fixtures(manifest_path: Path, fixtures: list[dict], stl_dir: Path) -> None:
    openscad_path = get_openscad_path()
    write_feature_fixture_library(manifest_path, stl_dir)
    for fixture in fixtures:
        scad_path = stl_dir / fixture["output_filename"]
        stl_path = stl_dir / f"{Path(fixture['output_filename']).stem}.stl"
        if stl_path.exists():
            continue
        log_path = stl_dir / f"{fixture['name']}.log"
        success = run_openscad(
            fixture["name"],
            ["--render", "-o", str(stl_path), str(scad_path)],
            str(log_path),
            openscad_path,
        )
        if not success:
            raise RuntimeError(f"OpenSCAD render failed: {fixture['name']}")


def _serialize_score(score: ManifestScore, fixtures: list[dict]) -> dict:
    return {
        "mean": score.mean,
        "by_type": score.by_type(fixtures),
        "per_fixture": [
            {
                "name": s.name,
                "count_score": s.count_score,
                "dimension_score": s.dimension_score,
                "total": s.total,
            }
            for s in score.per_fixture
        ],
    }


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_report(path: Path, **ctx) -> None:
    args = ctx["args"]
    lines = ["# Detector Auto-Tuning Report", "",
             f"- Trials: {args.trials}",
             f"- Seed: {args.seed}",
             f"- Train: {len(ctx['train'])} fixtures — Holdout: {len(ctx['holdout'])} fixtures",
             f"- Selected config source: {ctx['selected_config_source']}",
             "",
             "## Aggregate scores",
             "",
             "| Split | Baseline | Tuned | Delta |",
             "|---|---|---|---|",
             f"| Train | {ctx['baseline_train'].mean:.4f} | {ctx['tuned_train'].mean:.4f} | "
             f"{ctx['tuned_train'].mean - ctx['baseline_train'].mean:+.4f} |"]
    if ctx["baseline_holdout"] is not None and ctx["tuned_holdout"] is not None:
        train_gain = ctx["tuned_train"].mean - ctx["baseline_train"].mean
        holdout_gain = ctx["tuned_holdout"].mean - ctx["baseline_holdout"].mean
        overfit_gap = train_gain - holdout_gain
        lines.append(
            f"| Holdout | {ctx['baseline_holdout'].mean:.4f} | {ctx['tuned_holdout'].mean:.4f} | "
            f"{holdout_gain:+.4f} |"
        )
        lines.extend(["",
                      "## Overfit indicator",
                      "",
                      f"- Train gain: {train_gain:+.4f}",
                      f"- Holdout gain: {holdout_gain:+.4f}",
                      f"- Overfit gap (train gain − holdout gain): {overfit_gap:+.4f}",
                      "",
                      "A gap close to 0 means the tuned config generalises. A gap ≥ train gain",
                      "means the gain was entirely fixture-specific."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_cv_report(path: Path, fold_scores: list[float], fold_params: list[dict], fixtures: list[dict]) -> None:
    lines = ["# Cross-Validation Report", ""]
    mean_score = sum(fold_scores) / len(fold_scores) if fold_scores else 0.0
    std_score = statistics.stdev(fold_scores) if len(fold_scores) > 1 else 0.0

    lines.extend([
        f"- **Mean holdout score**: {mean_score:.4f}",
        f"- **Std dev across folds**: {std_score:.4f}",
        ""
    ])

    lines.extend(["## Per-fold scores", ""])
    for i, (score, fixture) in enumerate(zip(fold_scores, fixtures)):
        lines.append(f"- Fold {i + 1} (held out {fixture['name']}): {score:.4f}")
    lines.append("")

    lines.extend(["## Parameter Stability", ""])
    lines.append("A stable parameter is a credible signal. An unstable parameter is overfit.")
    lines.append("")

    param_values = defaultdict(list)
    for p in fold_params:
        for k, v in p.items():
            param_values[k].append(v)

    lines.extend(["| Parameter | Min | Max | Span | Mean | Std Dev |", "|---|---|---|---|---|---|"])
    for k, vals in sorted(param_values.items()):
        p_min, p_max = min(vals), max(vals)
        p_mean = sum(vals) / len(vals)
        p_std = statistics.stdev(vals) if len(vals) > 1 else 0.0
        span = p_max - p_min
        lines.append(f"| {k} | {p_min:.4f} | {p_max:.4f} | {span:.4f} | {p_mean:.4f} | {p_std:.4f} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
