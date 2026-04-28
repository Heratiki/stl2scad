"""Self-contained HTML reports for user-local STL corpus scores."""

from __future__ import annotations

import base64
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any

from stl2scad.tuning.progress import corpus_progress


BUCKET_ORDER = [
    "parametric_preview",
    "axis_pairs_only",
    "feature_graph_no_preview",
    "polyhedron_fallback",
    "error",
    "missing",
]
BUCKET_COLORS = {
    "parametric_preview": "#22c55e",
    "axis_pairs_only": "#f59e0b",
    "feature_graph_no_preview": "#f97316",
    "polyhedron_fallback": "#64748b",
    "error": "#ef4444",
    "missing": "#9ca3af",
}


def generate_thumbnail(stl_path: Path | str, sha256: str, cache_dir: Path | str) -> str:
    """Return a base64 PNG data URI for an STL thumbnail, or an empty string."""
    try:
        if not str(sha256).strip():
            return ""
        cache_path = Path(cache_dir) / f"{str(sha256)[:12]}.png"
        if cache_path.exists():
            return _png_data_uri(cache_path.read_bytes())

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _render_thumbnail_png(Path(stl_path), cache_path)
        if cache_path.exists():
            return _png_data_uri(cache_path.read_bytes())
    except Exception:
        return ""
    return ""


def generate_html_report(
    score_path: Path | str,
    output_path: Path | str,
    *,
    thumb_cache_dir: Path | str,
    show_progress: bool = True,
) -> Path:
    """Render a standalone local-corpus score report and return its path."""
    score_file = Path(score_path)
    if not score_file.exists():
        raise FileNotFoundError(f"Score JSON not found: {score_file}")

    score = json.loads(score_file.read_text(encoding="utf-8"))
    corpus_root = Path(str(score.get("corpus_root", "")))
    per_file = list(score.get("per_file") or [])
    triage_by_source = {
        str(row.get("source_file", "")): row
        for row in (score.get("triage", {}).get("per_file") or [])
    }

    iterable = per_file
    if show_progress:
        iterable = corpus_progress(
            per_file,
            desc="Rendering thumbnails",
            total=len(per_file),
        )

    rows = []
    for case in iterable:
        rows.append(_report_row(case, triage_by_source, corpus_root, thumb_cache_dir))

    html = _render_html(score, rows)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _render_thumbnail_png(stl_path: Path, output_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from stl import mesh as stl_mesh

    stl = stl_mesh.Mesh.from_file(str(stl_path))
    vectors = stl.vectors
    points = vectors.reshape(-1, 3)
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    center = (mins + maxs) / 2.0
    radius = max(float((maxs - mins).max()) / 2.0, 1e-6)

    fig = plt.figure(figsize=(2.8, 2.0), dpi=120)
    ax = fig.add_subplot(111, projection="3d")
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    collection = Poly3DCollection(
        vectors,
        facecolor="#5b8fb9",
        edgecolor="#dbeafe",
        linewidths=0.15,
        alpha=0.95,
    )
    ax.add_collection3d(collection)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=24, azim=-42)
    ax.set_axis_off()
    ax.set_proj_type("ortho")

    try:
        ax.dist = 7
    except Exception:
        pass
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(
            output_path,
            facecolor=fig.get_facecolor(),
            bbox_inches="tight",
            pad_inches=0,
        )
    finally:
        plt.close(fig)


def _png_data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _report_row(
    case: dict[str, Any],
    triage_by_source: dict[str, dict[str, Any]],
    corpus_root: Path,
    thumb_cache_dir: Path | str,
) -> dict[str, str]:
    rel_path = str(case.get("relative_path", ""))
    triage = triage_by_source.get(rel_path, {})
    bucket = str(triage.get("bucket") or case.get("status") or "missing")
    if bucket == "ok":
        bucket = "polyhedron_fallback"
    stl_path = corpus_root / rel_path
    if not stl_path.exists():
        bucket = "missing"

    sha256 = str(case.get("sha256", ""))
    if bucket != "missing" and not sha256:
        try:
            sha256 = hashlib.sha256(stl_path.read_bytes()).hexdigest()
        except Exception:
            sha256 = ""
    thumb = ""
    if bucket != "missing" and sha256:
        thumb = generate_thumbnail(stl_path, sha256, thumb_cache_dir)

    return {
        "relative_path": rel_path,
        "filename": Path(rel_path).name,
        "bucket": bucket,
        "thumb": thumb,
        "feature_info": _feature_info(bucket, case, triage),
    }


def _feature_info(
    bucket: str,
    case: dict[str, Any],
    triage: dict[str, Any],
) -> str:
    if bucket == "parametric_preview":
        return "parametric preview"
    if bucket == "axis_pairs_only":
        metadata = triage.get("failure_shape_metadata") or {}
        axis_pair_count = metadata.get("axis_pair_count", "-")
        return f"axis pairs: {axis_pair_count}"
    if bucket == "error":
        return _truncate(str(case.get("error") or triage.get("error") or "error"), 160)
    if bucket == "missing":
        return "missing STL"
    return bucket.replace("_", " ")


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _render_html(score: dict[str, Any], rows: list[dict[str, str]]) -> str:
    counts = _bucket_counts(score, rows)
    badges = "\n".join(
        f'<span class="summary-badge"><b>{escape(bucket)}</b> {counts.get(bucket, 0)}</span>'
        for bucket in BUCKET_ORDER
    )
    table_rows = "\n".join(_render_table_row(row) for row in rows)
    title = "Local Corpus Report"
    generated = escape(str(score.get("generated_at_utc", "-")))
    preview_ratio = float(score.get("preview_ready_ratio", 0.0))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  --text: #111827;
  --muted: #4b5563;
  --line: #d1d5db;
  --panel: #f8fafc;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--text);
  background: #ffffff;
}}
header {{
  padding: 24px 28px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}}
h1 {{ margin: 0 0 8px; font-size: 26px; }}
.meta {{ color: var(--muted); font-size: 14px; margin-bottom: 16px; }}
.summary {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.summary-badge {{
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 9px;
  background: #fff;
  font-size: 13px;
}}
main {{ padding: 20px 28px 32px; }}
table {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}}
th, td {{
  border-bottom: 1px solid var(--line);
  padding: 10px;
  text-align: left;
  vertical-align: middle;
  overflow-wrap: anywhere;
}}
th {{ font-size: 12px; text-transform: uppercase; color: var(--muted); }}
.thumb {{ width: 164px; }}
.thumb img {{
  display: block;
  width: 140px;
  height: 100px;
  object-fit: contain;
  background: #0f172a;
  border-radius: 6px;
}}
.placeholder {{
  display: grid;
  place-items: center;
  width: 140px;
  height: 100px;
  border: 1px dashed var(--line);
  border-radius: 6px;
  color: var(--muted);
  font-size: 12px;
}}
.badge {{
  display: inline-block;
  min-width: 12ch;
  border-radius: 6px;
  padding: 5px 8px;
  color: white;
  font-size: 12px;
  font-weight: 700;
}}
.file {{ font-family: Consolas, "Courier New", monospace; font-size: 13px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">
    Generated {generated} - files {int(score.get("files_present", 0))}/{int(score.get("files_total", 0))}
    - preview ready {preview_ratio:.1%}
  </div>
  <div class="summary">{badges}</div>
</header>
<main>
  <table>
    <thead>
      <tr><th class="thumb">Thumbnail</th><th>Filename</th><th>Bucket</th><th>Feature info</th></tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</main>
</body>
</html>
"""


def _bucket_counts(score: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, int]:
    counts = dict((score.get("triage", {}).get("bucket_counts") or {}))
    missing = sum(1 for row in rows if row["bucket"] == "missing")
    counts["missing"] = max(int(score.get("files_missing", 0)), missing)
    for bucket in BUCKET_ORDER:
        counts.setdefault(bucket, 0)
    return counts


def _render_table_row(row: dict[str, str]) -> str:
    bucket = row["bucket"]
    color = BUCKET_COLORS.get(bucket, "#64748b")
    thumb = (
        f'<img alt="{escape(row["filename"])} thumbnail" src="{row["thumb"]}">'
        if row["thumb"]
        else '<div class="placeholder">(no preview)</div>'
    )
    return (
        "<tr>"
        f'<td class="thumb">{thumb}</td>'
        f'<td class="file">{escape(row["relative_path"])}</td>'
        f'<td><span class="badge" style="background:{color}">{escape(bucket)}</span></td>'
        f"<td>{escape(row['feature_info'])}</td>"
        "</tr>"
    )
