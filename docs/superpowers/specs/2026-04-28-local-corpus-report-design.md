# Local Corpus HTML Report + Progress Bars — Design Spec

**Date:** 2026-04-28  
**Status:** Approved  
**Scope:** Add tqdm progress feedback to corpus scripts and a self-contained HTML report with STL thumbnails.

---

## Problem

The corpus scripts (`create_local_corpus.py`, `score_local_corpus.py`) produce no output during execution. On a 589-file corpus this means minutes of silence. There is also no visual summary of results after scoring — the user must parse raw JSON.

## Goals

1. Terminal progress bars during manifest creation and scoring.
2. Self-contained HTML report from a score JSON, with per-file STL thumbnails, bucket badges, and feature details for `parametric_preview` hits.
3. Thumbnail cache so regenerating the report is fast.
4. Standalone report CLI so the HTML can be regenerated without re-running the detector.

## Out of Scope (Future)

- Live HTML dashboard that updates as files process (Option C from brainstorming). Tracked as a future upgrade in `docs/planning/feature_level_reconstruction.md`.

---

## Architecture

### New files

| File | Purpose |
|---|---|
| `stl2scad/tuning/progress.py` | Thin tqdm wrapper; no-ops if tqdm not installed |
| `stl2scad/tuning/html_report.py` | Thumbnail generator + HTML template renderer |
| `scripts/report_local_corpus.py` | Standalone CLI: score JSON → HTML |

### Modified files

| File | Change |
|---|---|
| `stl2scad/tuning/local_corpus.py` | Accept optional `progress_fn` callback in `score_local_corpus()` and `create_local_corpus_manifest()` |
| `scripts/score_local_corpus.py` | Add `--html-report` and `--thumb-cache` flags |
| `scripts/create_local_corpus.py` | Add progress bar during STL scan |
| `setup.py` | Already updated: `reporting` extra declares tqdm, pyglet<2, matplotlib, pillow, trimesh, networkx |

---

## Component Design

### `stl2scad/tuning/progress.py`

Single public function:

```python
def corpus_progress(iterable, *, desc: str, total: int | None = None):
    ...
```

- If `tqdm` is importable: wraps iterable in `tqdm.tqdm(iterable, desc=desc, total=total, unit="file")`.
- If not: yields items and prints `desc: N/total` every 10% to stdout.
- Never raises; progress is best-effort.

### `stl2scad/tuning/html_report.py`

Two public functions:

**`generate_thumbnail(stl_path, sha256, cache_dir) -> str`**
- Cache key: `<cache_dir>/<sha256[:12]>.png`
- Cache hit: read file, return base64 data URI.
- Cache miss: render via matplotlib + numpy-stl (Poly3DCollection, dark background, steel-blue mesh, correct aspect ratio). Save PNG to cache. Return base64 data URI.
- On any render error: return empty string (report shows placeholder).

**`generate_html_report(score_path, output_path, *, thumb_cache_dir, show_progress=True) -> Path`**
- Reads score JSON.
- For each case in `per_file`, resolves STL path from `corpus_root`, calls `generate_thumbnail`.
- Renders HTML template (inline CSS, no external CDN).
- Writes single self-contained `.html` file.
- Returns output path.

#### HTML structure

```
<header>  Summary bar: files_total / files_present / preview_ready_ratio / bucket counts
<table>
  <tr> thumbnail | filename | bucket badge | feature info
```

Bucket badge colors:
- `parametric_preview` → green (`#22c55e`)
- `axis_pairs_only` → amber (`#f59e0b`)
- `feature_graph_no_preview` → orange (`#f97316`)
- `polyhedron_fallback` → blue-gray (`#64748b`)
- `error` → red (`#ef4444`)
- `missing` → gray (`#9ca3af`)

Feature info column: for `parametric_preview` rows, show "parametric preview" label (triage per_file carries no sub-detail for passing files; full feature breakdown would require re-running the graph and is out of scope here). For `axis_pairs_only` rows, show `axis_pair_count` from `failure_shape_metadata`. For `error` rows, show truncated error string.

HTML is pure HTML/CSS — no JavaScript, no external URLs. Works fully offline.

### `scripts/report_local_corpus.py`

```
python scripts/report_local_corpus.py \
  --score artifacts/local_corpus_score.json \
  --output artifacts/local_corpus_report.html \
  --thumb-cache artifacts/thumbs
```

All args have defaults matching the above paths.

### `scripts/score_local_corpus.py` additions

New flags:
- `--html-report` (flag, default off) — generate HTML report after scoring
- `--html-output` (default `artifacts/local_corpus_report.html`)
- `--thumb-cache` (default `artifacts/thumbs`)

### `stl2scad/tuning/local_corpus.py` changes

`score_local_corpus()` and `create_local_corpus_manifest()` accept an optional `progress_fn` parameter (callable matching `corpus_progress` signature). Scripts pass in `corpus_progress`; library default is `None` (no progress, keeps library side-effect-free).

---

## Thumbnail Cache

- Location: `artifacts/thumbs/` (add to `.gitignore`)
- Filename: `<sha256[:12]>.png`
- Stale detection: implicit — SHA256 changes when file changes, so old cache entry is simply never hit (no cleanup needed)
- Size: ~13 kB per file × 589 files ≈ 7.6 MB total

---

## Error Handling

- Missing tqdm: silent fallback to print-based progress.
- STL render failure: thumbnail cell shows `(no preview)` text, report continues.
- Missing score JSON: `report_local_corpus.py` exits with clear error message.
- Score JSON referencing missing STL files: thumbnail skipped, bucket badge shows `missing`.

---

## Testing

- Unit test for `generate_thumbnail` cache hit/miss using a fixture STL (e.g., `primitive_box_axis_aligned.stl` from benchmark fixtures).
- Unit test for `generate_html_report` using existing `artifacts/local_corpus_score.json` or a minimal synthetic score dict — assert output file exists, contains bucket badge strings, contains `<img` tags.
- Unit test for `corpus_progress` with tqdm absent (mock import failure) — assert iteration still completes.
- No new fixture STL files needed.

---

## Future: Live Dashboard (Option C)

When this static report proves useful and the user wants live feedback during runs, the upgrade path is:
- Score script writes incremental JSON to a temp file as each STL is processed.
- A browser tab polls that file (or a local HTTP server streams SSE).
- Track in `docs/planning/feature_level_reconstruction.md` under a "Tooling" section.
