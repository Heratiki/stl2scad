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
import sys
from pathlib import Path

import optuna

from stl2scad.core.converter import get_openscad_path, run_openscad
from stl2scad.core.feature_fixtures import (
    load_feature_fixture_manifest,
    write_feature_fixture_library,
)
from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.scoring import ManifestScore, score_manifest
from stl2scad.tuning.search_space import suggest_config
from stl2scad.tuning.splits import stratified_split

logger = logging.getLogger(__name__)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="tests/data/feature_fixtures_manifest.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--holdout-ratio", type=float, default=0.25)
    args = parser.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = load_feature_fixture_manifest(Path(args.manifest))

    stl_dir = args.output / "fixtures"
    stl_dir.mkdir(exist_ok=True)
    _render_fixtures(Path(args.manifest), fixtures, stl_dir)

    train, holdout = stratified_split(fixtures, holdout_ratio=args.holdout_ratio, seed=args.seed)
    logger.info("Train: %d fixtures, Holdout: %d fixtures", len(train), len(holdout))

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
    best_config = _reconstruct_config(study.best_params)
    _dump(args.output / "best_config.json", dataclasses.asdict(best_config))
    logger.info("Best train score: %.4f", study.best_value)

    tuned_train = score_manifest(best_config, train, stl_dir)
    tuned_holdout = score_manifest(best_config, holdout, stl_dir) if holdout else None
    _dump(args.output / "train_scores.json", _serialize_score(tuned_train, train))
    if tuned_holdout is not None:
        _dump(args.output / "holdout_scores.json", _serialize_score(tuned_holdout, holdout))

    baseline_train = score_manifest(DetectorConfig(), train, stl_dir)
    baseline_holdout = score_manifest(DetectorConfig(), holdout, stl_dir) if holdout else None

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
    )
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
