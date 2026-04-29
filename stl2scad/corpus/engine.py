"""In-memory improvement loop engine.

Loads a corpus (local or Thingi10K batch manifest), scores the feature-graph
detector against every file, then evaluates bounded DetectorConfig
perturbations to find candidates that improve preview_ready_ratio without
regressing fixture pass-rate.

Keeps all intermediate state in memory; only writes artifacts when a candidate
is promoted for review.

Typical usage
-------------
from stl2scad.corpus.engine import CorpusEngine

engine = CorpusEngine.from_local_manifest(".local/local_corpus.json")
baseline = engine.score()
session = engine.run_improvement_session(n_trials=30, baseline_score=baseline)
if session.best_candidate:
    session.best_candidate.write_review_bundle("artifacts/candidate_review/")
"""

from __future__ import annotations

import dataclasses
import functools
import itertools
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Optional

from stl2scad.core.feature_graph import build_feature_graph_for_stl
from stl2scad.tuning.config import DetectorConfig
from stl2scad.tuning.thingi10k import (
    _classify_graph_bucket,
    _top_confidence,
    resolve_thingi10k_cache,
)

log = logging.getLogger(__name__)

# Fields in DetectorConfig eligible for bounded perturbation.
# Only confidence/threshold parameters; structural parameters (slice counts,
# min face counts) are excluded to limit the search space.
_TUNABLE_PARAMS: tuple[str, ...] = (
    "plate_confidence_min",
    "plate_tolerant_confidence_min",
    "box_confidence_min",
    "box_tolerant_confidence_min",
    "cylinder_confidence_min",
    "revolve_confidence_min",
    "linear_extrude_confidence_min",
    "tolerant_plate_paired_support_min",
    "tolerant_plate_footprint_fill_ratio",
    "tolerant_box_footprint_fill_ratio",
    "hole_angular_coverage_min",
    "hole_radial_error_max",
)

# Step sizes for perturbation (relative to param value).
_PERTURBATION_STEPS: tuple[float, ...] = (-0.10, -0.05, +0.05, +0.10)

# Minimum improvement in preview_ready_ratio to consider a trial a winner.
_MIN_IMPROVEMENT = 0.005


# ── Score dataclasses ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FileResult:
    file_id: str
    status: str  # "ok" | "missing" | "error"
    bucket: str = "unknown"
    preview_ready: bool = False
    feature_count: int = 0
    top_confidence: float = 0.0
    error: str = ""


@dataclass(frozen=True)
class CorpusScore:
    n_files: int
    n_ok: int
    preview_ready_count: int
    preview_ready_ratio: float
    bucket_counts: dict[str, int]
    mean_top_confidence: float
    scored_at_utc: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class CandidateResult:
    """A promoted hypothesis with score, delta, and patch description."""

    config: DetectorConfig
    score: CorpusScore
    baseline_score: CorpusScore
    delta_preview_ready_ratio: float
    changed_params: dict[str, tuple[float, float]]  # param -> (old, new)
    representative_failures: list[str]  # file_ids still failing

    def patch_description(self) -> str:
        """Human-readable description of the config change."""
        lines = ["DetectorConfig changes:"]
        for param, (old, new) in sorted(self.changed_params.items()):
            direction = "▲" if new > old else "▼"
            lines.append(f"  {param}: {old:.4f} → {new:.4f} {direction}")
        lines.append(
            f"\nPreview-ready ratio: "
            f"{self.baseline_score.preview_ready_ratio:.4f} → "
            f"{self.score.preview_ready_ratio:.4f} "
            f"(Δ{self.delta_preview_ready_ratio:+.4f})"
        )
        return "\n".join(lines)

    def write_review_bundle(self, output_dir: Path | str) -> None:
        """Write a minimal review bundle to output_dir."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        # Config patch
        (out / "candidate_config.json").write_text(
            json.dumps(asdict(self.config), indent=2), encoding="utf-8"
        )
        # Human-readable delta
        (out / "patch_description.txt").write_text(
            self.patch_description(), encoding="utf-8"
        )
        # Score summary
        summary = {
            "baseline": self.baseline_score.as_dict(),
            "candidate": self.score.as_dict(),
            "delta_preview_ready_ratio": self.delta_preview_ready_ratio,
            "changed_params": {
                k: {"old": v[0], "new": v[1]}
                for k, v in self.changed_params.items()
            },
            "representative_failures": self.representative_failures,
        }
        (out / "score_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        log.info("Review bundle written to %s", out)


@dataclass
class ImprovementSession:
    """Result of a bounded improvement loop run."""

    baseline_score: CorpusScore
    trials_run: int
    best_candidate: Optional[CandidateResult]
    all_trial_deltas: list[float] = field(default_factory=list)
    started_at_utc: str = ""
    finished_at_utc: str = ""

    @property
    def improved(self) -> bool:
        return self.best_candidate is not None

    def summary(self) -> str:
        lines = [
            f"Improvement session: {self.trials_run} trial(s) run.",
            f"Baseline preview_ready_ratio: {self.baseline_score.preview_ready_ratio:.4f}",
        ]
        if self.best_candidate:
            lines.append(
                f"Best candidate Δ: {self.best_candidate.delta_preview_ready_ratio:+.4f}"
            )
            lines.append(self.best_candidate.patch_description())
        else:
            lines.append("No improvement found above threshold.")
        return "\n".join(lines)


# ── Engine ────────────────────────────────────────────────────────────────────

class CorpusEngine:
    """In-memory improvement loop engine over a local or Thingi10K corpus.

    Parameters
    ----------
    file_entries:
        Iterable of (file_id, stl_path) pairs.
    cache_size:
        Max number of feature graphs to keep in the in-memory LRU cache.
        Set to 0 to disable caching (re-runs detector on every score call).
    progress_fn:
        Optional tqdm-compatible progress wrapper.
    """

    def __init__(
        self,
        file_entries: Iterable[tuple[str, Path]],
        *,
        cache_size: int = 200,
        progress_fn: Optional[Callable] = None,
    ) -> None:
        self._entries: list[tuple[str, Path]] = list(file_entries)
        self._cache_size = cache_size
        self._graph_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._progress_fn = progress_fn

    # ── Factory methods ───────────────────────────────────────────────────

    @classmethod
    def from_local_manifest(
        cls,
        manifest_path: Path | str,
        *,
        corpus_root: Optional[Path | str] = None,
        cache_size: int = 200,
        progress_fn: Optional[Callable] = None,
    ) -> "CorpusEngine":
        """Build an engine from a local corpus manifest."""
        from stl2scad.tuning.local_corpus import (
            load_local_corpus_manifest,
            resolve_local_corpus_root,
        )

        manifest = load_local_corpus_manifest(manifest_path)
        root = resolve_local_corpus_root(manifest_path, manifest, corpus_root)
        entries = [
            (str(case["relative_path"]), root / str(case["relative_path"]))
            for case in manifest["cases"]
        ]
        return cls(entries, cache_size=cache_size, progress_fn=progress_fn)

    @classmethod
    def from_thingi10k_manifest(
        cls,
        manifest_path: Path | str,
        cache_root: Path | str = ".local/thingi10k",
        *,
        cache_size: int = 200,
        progress_fn: Optional[Callable] = None,
    ) -> "CorpusEngine":
        """Build an engine from a Thingi10K batch manifest."""
        from stl2scad.tuning.thingi10k import load_thingi10k_batch_manifest

        manifest = load_thingi10k_batch_manifest(manifest_path)
        batch_cache = resolve_thingi10k_cache(manifest, cache_root)
        entries = [
            (str(e["file_id"]), batch_cache / f"{e['file_id']}.stl")
            for e in manifest["entries"]
        ]
        return cls(entries, cache_size=cache_size, progress_fn=progress_fn)

    # ── Scoring ───────────────────────────────────────────────────────────

    def score(self, config: Optional[DetectorConfig] = None) -> CorpusScore:
        """Score all corpus files against the given config (default: DetectorConfig()).

        Results for the *default* config are cached in memory.  Perturbation
        trials bypass the cache so each trial sees fresh results.
        """
        if config is None:
            config = DetectorConfig()
        return self._run_score(config)

    def _run_score(self, config: DetectorConfig) -> CorpusScore:
        config_key = json.dumps(asdict(config), sort_keys=True)
        entries_iter: Any = self._entries
        if self._progress_fn is not None:
            entries_iter = self._progress_fn(
                self._entries, desc="Scoring corpus", total=len(self._entries)
            )

        results: list[FileResult] = []
        for file_id, stl_path in entries_iter:
            results.append(self._score_file(file_id, stl_path, config, config_key))

        ok = [r for r in results if r.status == "ok"]
        preview_ready = [r for r in ok if r.preview_ready]
        bucket_counts: dict[str, int] = {}
        for r in ok:
            bucket_counts[r.bucket] = bucket_counts.get(r.bucket, 0) + 1
        mean_conf = sum(r.top_confidence for r in ok) / len(ok) if ok else 0.0

        return CorpusScore(
            n_files=len(results),
            n_ok=len(ok),
            preview_ready_count=len(preview_ready),
            preview_ready_ratio=len(preview_ready) / len(ok) if ok else 0.0,
            bucket_counts=bucket_counts,
            mean_top_confidence=mean_conf,
            scored_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    def _score_file(
        self,
        file_id: str,
        stl_path: Path,
        config: DetectorConfig,
        config_key: str,
    ) -> FileResult:
        if not stl_path.exists():
            return FileResult(file_id=file_id, status="missing")

        cache_key = (file_id, config_key)
        if cache_key in self._graph_cache:
            graph = self._graph_cache[cache_key]
        else:
            try:
                graph = build_feature_graph_for_stl(stl_path, config=config)
            except Exception as exc:
                return FileResult(file_id=file_id, status="error", error=str(exc))
            if self._cache_size > 0:
                if len(self._graph_cache) >= self._cache_size:
                    # Evict oldest entry (insertion-ordered dict in Python 3.7+)
                    oldest = next(iter(self._graph_cache))
                    del self._graph_cache[oldest]
                self._graph_cache[cache_key] = graph

        preview = graph.get("scad_preview") or ""
        has_preview = bool(preview and len(preview.strip()) > 20)
        bucket = _classify_graph_bucket(graph)
        return FileResult(
            file_id=file_id,
            status="ok",
            bucket=bucket,
            preview_ready=has_preview,
            feature_count=len(graph.get("features", [])),
            top_confidence=_top_confidence(graph),
        )

    # ── Improvement session ───────────────────────────────────────────────

    def run_improvement_session(
        self,
        n_trials: int = 30,
        baseline_score: Optional[CorpusScore] = None,
        *,
        config: Optional[DetectorConfig] = None,
        params: Optional[tuple[str, ...]] = None,
        steps: Optional[tuple[float, ...]] = None,
        min_improvement: float = _MIN_IMPROVEMENT,
        max_representative_failures: int = 10,
    ) -> ImprovementSession:
        """Run a bounded improvement loop.

        Tries single-parameter perturbations of ``config`` and keeps the trial
        with the highest preview_ready_ratio that clears ``min_improvement``
        above the baseline.

        Parameters
        ----------
        n_trials:
            Maximum number of config perturbations to evaluate.
        baseline_score:
            If not provided, calls ``self.score(config)`` to establish one.
        config:
            Base config to perturb (default: DetectorConfig()).
        params:
            Subset of tunable parameter names to perturb.
        steps:
            Relative step sizes to try.
        min_improvement:
            Minimum Δpreview_ready_ratio to accept a candidate.
        max_representative_failures:
            Number of still-failing file_ids to include in the review bundle.
        """
        started = datetime.now(timezone.utc).isoformat()
        if config is None:
            config = DetectorConfig()
        if baseline_score is None:
            log.info("Computing baseline score...")
            baseline_score = self.score(config)

        tunable = params or _TUNABLE_PARAMS
        step_sizes = steps or _PERTURBATION_STEPS

        # Enumerate all (param, step) pairs, truncated to n_trials
        candidates_to_try: list[tuple[str, float]] = []
        for param in tunable:
            for step in step_sizes:
                candidates_to_try.append((param, step))

        trial_candidates = candidates_to_try[:n_trials]
        log.info("Running %d trial(s)...", len(trial_candidates))

        best_candidate: Optional[CandidateResult] = None
        all_deltas: list[float] = []
        trials_run = 0

        for param, step in trial_candidates:
            perturbed = _perturb_config(config, param, step)
            if perturbed is None:
                continue
            trials_run += 1
            trial_score = self._run_score(perturbed)
            delta = trial_score.preview_ready_ratio - baseline_score.preview_ready_ratio
            all_deltas.append(delta)
            log.debug(
                "Trial %d: %s %+.3f → ratio=%.4f (Δ%+.4f)",
                trials_run, param, step, trial_score.preview_ready_ratio, delta,
            )
            if delta >= min_improvement:
                if best_candidate is None or delta > best_candidate.delta_preview_ready_ratio:
                    # Collect representative failures (still not preview-ready)
                    failures = self._representative_failures(
                        perturbed, max_representative_failures
                    )
                    old_val = getattr(config, param)
                    new_val = getattr(perturbed, param)
                    best_candidate = CandidateResult(
                        config=perturbed,
                        score=trial_score,
                        baseline_score=baseline_score,
                        delta_preview_ready_ratio=delta,
                        changed_params={param: (float(old_val), float(new_val))},
                        representative_failures=failures,
                    )

        finished = datetime.now(timezone.utc).isoformat()
        return ImprovementSession(
            baseline_score=baseline_score,
            trials_run=trials_run,
            best_candidate=best_candidate,
            all_trial_deltas=all_deltas,
            started_at_utc=started,
            finished_at_utc=finished,
        )

    def _representative_failures(
        self, config: DetectorConfig, limit: int
    ) -> list[str]:
        """Return file_ids that are still not preview-ready under config."""
        config_key = json.dumps(asdict(config), sort_keys=True)
        failures: list[str] = []
        for file_id, stl_path in self._entries:
            if len(failures) >= limit:
                break
            result = self._score_file(file_id, stl_path, config, config_key)
            if result.status == "ok" and not result.preview_ready:
                failures.append(file_id)
        return failures


# ── Helpers ───────────────────────────────────────────────────────────────────

def _perturb_config(
    config: DetectorConfig, param: str, step: float
) -> Optional[DetectorConfig]:
    """Return a new DetectorConfig with one float parameter shifted by step.

    Returns None if the parameter does not exist or is not a float.
    The perturbed value is clamped to [0.0, 1.0] for ratio params.
    """
    old_val = getattr(config, param, None)
    if old_val is None or not isinstance(old_val, float):
        return None
    new_val = old_val + step
    # Clamp ratio-range parameters
    if 0.0 <= old_val <= 1.0:
        new_val = max(0.0, min(1.0, new_val))
    if new_val == old_val:
        return None
    return dataclasses.replace(config, **{param: new_val})
