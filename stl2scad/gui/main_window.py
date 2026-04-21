"""
Main window implementation for the STL to OpenSCAD converter GUI.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np
from PyQt5 import QtWidgets
from PyQt5.QtCore import (
    QThread,
    Qt,
    pyqtSignal,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
)
from PyQt5.QtGui import QColor, QPixmap, QFont, QPalette, QIcon
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QPlainTextEdit,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QFrame,
    QSizePolicy,
    QProgressBar,
    QPushButton,
    QCheckBox,
    QGroupBox,
    QSpacerItem,
    QScrollArea,
    QStatusBar,
    QAction,
)
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from stl import mesh

from stl2scad.core.acceleration import get_acceleration_report
from stl2scad.core.converter import ConversionStats, stl2scad
from stl2scad.core.feature_graph import (
    build_feature_graph_for_folder,
    build_feature_graph_for_stl,
    emit_feature_graph_scad_preview,
)
from stl2scad.core.feature_inventory import (
    InventoryConfig,
    analyze_stl_folder,
    analyze_stl_folder_for_feature_graphs,
    build_feature_graphs_from_inventory,
)
from stl2scad.core.recognition import (
    SUPPORTED_RECOGNITION_BACKENDS,
    get_available_recognition_backends,
)
from stl2scad.core.verification import (
    generate_comparison_visualization,
    generate_verification_report_html,
    verify_conversion,
)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
PALETTE = {
    "bg": "#16161d",
    "panel": "#1f1f2b",
    "panel_alt": "#252534",
    "border": "#35354a",
    "accent": "#e8682a",
    "accent_dk": "#c0531f",
    "text": "#d8d8e8",
    "text_dim": "#888899",
    "success": "#4ec98a",
    "warning": "#f0b84a",
    "error": "#e05555",
    "highlight": "#2e2e42",
}

APP_STYLESHEET = f"""
/* ── Global ── */
QMainWindow, QWidget {{
    background-color: {PALETTE["bg"]};
    color: {PALETTE["text"]};
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}}

/* ── Sidebar panel ── */
#sidebar {{
    background-color: {PALETTE["panel"]};
    border-right: 1px solid {PALETTE["border"]};
    min-width: 260px;
    max-width: 260px;
}}

/* ── Section group boxes ── */
QGroupBox {{
    background-color: {PALETTE["panel_alt"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 4px;
    margin-top: 14px;
    padding: 8px 6px 8px 6px;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1.5px;
    color: {PALETTE["text_dim"]};
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    top: 2px;
}}

/* ── Primary button ── */
QPushButton#primary {{
    background-color: {PALETTE["accent"]};
    color: #ffffff;
    border: none;
    border-radius: 3px;
    padding: 8px 0;
    font-family: "Consolas", monospace;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.8px;
}}
QPushButton#primary:hover {{
    background-color: {PALETTE["accent_dk"]};
}}
QPushButton#primary:disabled {{
    background-color: #3a3a50;
    color: {PALETTE["text_dim"]};
}}

/* ── Secondary button ── */
QPushButton#secondary {{
    background-color: transparent;
    color: {PALETTE["text"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 3px;
    padding: 6px 0;
    font-family: "Consolas", monospace;
    font-size: 11px;
}}
QPushButton#secondary:hover {{
    background-color: {PALETTE["highlight"]};
    border-color: {PALETTE["accent"]};
    color: {PALETTE["accent"]};
}}
QPushButton#secondary:disabled {{
    color: {PALETTE["text_dim"]};
    border-color: #2a2a3a;
}}
QPushButton#secondary:checked {{
    background-color: {PALETTE["highlight"]};
    border-color: {PALETTE["accent"]};
    color: {PALETTE["accent"]};
}}

/* ── View overlay buttons ── */
QPushButton#overlay {{
    background-color: rgba(31, 31, 43, 180);
    color: {PALETTE["text"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 10px;
}}
QPushButton#overlay:hover {{
    background-color: rgba(46, 46, 66, 200);
    border-color: {PALETTE["accent"]};
}}

/* ── Spin boxes ── */
QDoubleSpinBox, QSpinBox, QComboBox {{
    background-color: {PALETTE["bg"]};
    color: {PALETTE["text"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 2px;
    padding: 2px 4px;
    font-family: "Consolas", monospace;
    font-size: 11px;
}}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {PALETTE["accent"]};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {PALETTE["panel_alt"]};
    border: none;
    width: 14px;
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {PALETTE["panel_alt"]};
    color: {PALETTE["text"]};
    border: 1px solid {PALETTE["border"]};
    selection-background-color: {PALETTE["highlight"]};
    selection-color: {PALETTE["accent"]};
}}

/* ── Checkboxes ── */
QCheckBox {{
    spacing: 6px;
    font-size: 11px;
    color: {PALETTE["text"]};
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {PALETTE["border"]};
    border-radius: 2px;
    background-color: {PALETTE["bg"]};
}}
QCheckBox::indicator:checked {{
    background-color: {PALETTE["accent"]};
    border-color: {PALETTE["accent"]};
}}

/* ── Labels ── */
QLabel#heading {{
    font-size: 11px;
    font-weight: bold;
    color: {PALETTE["accent"]};
    letter-spacing: 1px;
}}
QLabel#step_num {{
    font-size: 18px;
    font-weight: bold;
    color: {PALETTE["border"]};
}}
QLabel#file_display {{
    background-color: {PALETTE["bg"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 2px;
    padding: 4px 6px;
    color: {PALETTE["text_dim"]};
    font-size: 10px;
}}
QLabel#metric {{
    font-size: 10px;
    color: {PALETTE["text_dim"]};
}}

/* ── Progress bar ── */
QProgressBar {{
    background-color: {PALETTE["panel"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 2px;
    height: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {PALETTE["accent"]};
    border-radius: 2px;
}}

/* ── Status bar ── */
QStatusBar {{
    background-color: {PALETTE["panel"]};
    border-top: 1px solid {PALETTE["border"]};
    color: {PALETTE["text_dim"]};
    font-size: 11px;
}}

/* ── Scroll area ── */
QScrollArea {{
    border: none;
    background-color: {PALETTE["panel"]};
}}
QScrollBar:vertical {{
    background: {PALETTE["panel"]};
    width: 6px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE["border"]};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ── Separator ── */
QFrame#hsep {{
    background-color: {PALETTE["border"]};
    max-height: 1px;
    min-height: 1px;
}}
"""


# ---------------------------------------------------------------------------
# Worker threads (unchanged logic)
# ---------------------------------------------------------------------------


class ConversionWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        input_file,
        output_file,
        tolerance=1e-6,
        debug=False,
        parametric=False,
        recognition_backend="native",
        compute_backend="auto",
    ):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.tolerance = tolerance
        self.debug = debug
        self.parametric = parametric
        self.recognition_backend = recognition_backend
        self.compute_backend = compute_backend

    def run(self):
        try:
            self.progress.emit("Converting STL to SCAD…")
            stats = stl2scad(
                self.input_file,
                self.output_file,
                self.tolerance,
                self.debug,
                self.parametric,
                recognition_backend=self.recognition_backend,
                compute_backend=self.compute_backend,
            )
            self.finished.emit(stats)
        except Exception as exc:
            self.error.emit(str(exc))


class VerificationWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        stl_file,
        scad_file,
        tolerance,
        conversion_tolerance,
        parametric,
        recognition_backend,
        compute_backend,
        regenerate_scad,
        visualize,
        html_report,
        sample_seed,
    ):
        super().__init__()
        self.stl_file = stl_file
        self.scad_file = scad_file
        self.tolerance = tolerance
        self.conversion_tolerance = conversion_tolerance
        self.parametric = parametric
        self.recognition_backend = recognition_backend
        self.compute_backend = compute_backend
        self.regenerate_scad = regenerate_scad
        self.visualize = visualize
        self.html_report = html_report
        self.sample_seed = sample_seed

    def run(self):
        try:
            self.progress.emit("Preparing SCAD file for verification…")
            if self.regenerate_scad:
                stl2scad(
                    self.stl_file,
                    self.scad_file,
                    tolerance=self.conversion_tolerance,
                    parametric=self.parametric,
                    recognition_backend=self.recognition_backend,
                    compute_backend=self.compute_backend,
                )
            elif not os.path.exists(self.scad_file):
                raise FileNotFoundError(f"SCAD file not found: {self.scad_file}")

            self.progress.emit("Running geometric verification…")
            result = verify_conversion(
                self.stl_file,
                self.scad_file,
                self.tolerance,
                debug=False,
                sample_seed=self.sample_seed,
            )

            report_dir = os.path.dirname(self.scad_file) or os.path.dirname(
                self.stl_file
            )
            report_base = os.path.splitext(os.path.basename(self.stl_file))[0]
            report_file = os.path.join(report_dir, f"{report_base}_verification.json")
            result.save_report(report_file)

            visualizations: Dict[str, str] = {}
            html_file: Optional[str] = None
            vis_paths = {}

            if self.visualize or self.html_report:
                self.progress.emit("Generating visualization artifacts…")
                vis_dir = os.path.join(report_dir, f"{report_base}_visualizations")
                vis_paths = generate_comparison_visualization(
                    self.stl_file, self.scad_file, vis_dir
                )
                visualizations = {k: str(v) for k, v in vis_paths.items()}

            if self.html_report:
                self.progress.emit("Generating HTML report…")
                html_file = os.path.join(report_dir, f"{report_base}_verification.html")
                generate_verification_report_html(vars(result), vis_paths, html_file)

            self.finished.emit(
                {
                    "result": result,
                    "scad_file": self.scad_file,
                    "report_file": report_file,
                    "visualizations": visualizations,
                    "html_file": html_file,
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class BatchWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        input_dir,
        output_dir,
        tolerance,
        html_report,
        parametric,
        recognition_backend,
        compute_backend,
        sample_seed,
    ):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.tolerance = tolerance
        self.html_report = html_report
        self.parametric = parametric
        self.recognition_backend = recognition_backend
        self.compute_backend = compute_backend
        self.sample_seed = sample_seed

    def run(self):
        try:
            input_path = Path(self.input_dir)
            output_path = Path(self.output_dir)
            if not input_path.exists() or not input_path.is_dir():
                raise FileNotFoundError(f"Input directory not found: {self.input_dir}")

            output_path.mkdir(exist_ok=True, parents=True)
            stl_files = list(input_path.glob("**/*.stl"))
            if not stl_files:
                raise FileNotFoundError(f"No STL files found in {self.input_dir}")

            results: Dict[str, Dict[str, Any]] = {}
            total = len(stl_files)
            for index, stl_file in enumerate(stl_files, 1):
                rel_path = stl_file.relative_to(input_path)
                scad_file = output_path / rel_path.with_suffix(".scad")
                report_file = output_path / rel_path.with_suffix(".verification.json")
                scad_file.parent.mkdir(exist_ok=True, parents=True)
                self.progress.emit(
                    f"[{index}/{total}] Processing {stl_file.name}…"
                )

                try:
                    stl2scad(
                        str(stl_file),
                        str(scad_file),
                        parametric=self.parametric,
                        recognition_backend=self.recognition_backend,
                        compute_backend=self.compute_backend,
                    )
                    result = verify_conversion(
                        stl_file,
                        scad_file,
                        self.tolerance,
                        debug=False,
                        sample_seed=self.sample_seed,
                    )
                    result.save_report(report_file)

                    html_file = None
                    if self.html_report:
                        vis_dir = output_path / rel_path.with_suffix(".visualizations")
                        vis_dir.mkdir(exist_ok=True, parents=True)
                        visualizations = generate_comparison_visualization(
                            stl_file,
                            scad_file,
                            vis_dir,
                        )
                        html_file = output_path / rel_path.with_suffix(
                            ".verification.html"
                        )
                        generate_verification_report_html(
                            vars(result), visualizations, html_file
                        )

                    results[str(rel_path)] = {
                        "passed": result.passed,
                        "report": str(report_file),
                    }
                    if html_file is not None:
                        results[str(rel_path)]["html"] = str(html_file)
                except Exception as exc:
                    results[str(rel_path)] = {
                        "passed": False,
                        "error": str(exc),
                    }

            summary = {
                "total": len(results),
                "passed": sum(1 for item in results.values() if item.get("passed")),
                "failed": sum(1 for item in results.values() if not item.get("passed")),
                "results": results,
            }
            summary_file = output_path / "batch_summary.json"
            with summary_file.open("w", encoding="utf-8") as summary_handle:
                json.dump(summary, summary_handle, indent=2)

            self.finished.emit(
                {
                    "summary": summary,
                    "summary_file": str(summary_file),
                    "output_dir": str(output_path),
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class FeatureInventoryWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        input_dir,
        output_json,
        recursive,
        max_files,
        workers,
    ):
        super().__init__()
        self.input_dir = input_dir
        self.output_json = output_json
        self.recursive = recursive
        self.max_files = max_files
        self.workers = workers

    def run(self):
        try:
            report = analyze_stl_folder(
                input_dir=Path(self.input_dir),
                output_json=Path(self.output_json),
                config=InventoryConfig(
                    recursive=self.recursive,
                    max_files=self.max_files,
                    workers=self.workers,
                ),
                progress_callback=lambda done, total, path: self.progress.emit(
                    f"[inventory {done}/{total}] {Path(path).name}"
                ),
            )
            self.finished.emit(
                {
                    "report": report,
                    "output_json": self.output_json,
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class FeatureGraphWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, mode: str, **kwargs):
        super().__init__()
        self.mode = mode
        self.kwargs = kwargs

    def run(self):
        try:
            if self.mode == "single_file":
                input_path = Path(self.kwargs["input_path"])
                output_json = Path(self.kwargs["output_json"])
                graph = build_feature_graph_for_stl(input_path)
                output_json.parent.mkdir(parents=True, exist_ok=True)
                with output_json.open("w", encoding="utf-8") as handle:
                    json.dump(graph, handle, indent=2)

                preview_path = self.kwargs.get("preview_path")
                preview_written = None
                if preview_path:
                    scad = emit_feature_graph_scad_preview(graph)
                    if scad is not None:
                        preview_written = str(_write_text_file(preview_path, scad))

                self.finished.emit(
                    {
                        "mode": self.mode,
                        "report": graph,
                        "output_json": str(output_json),
                        "preview_path": preview_written,
                    }
                )
                return

            if self.mode == "folder":
                input_path = Path(self.kwargs["input_path"])
                output_json = Path(self.kwargs["output_json"])
                recursive = bool(self.kwargs["recursive"])
                max_files = self.kwargs["max_files"]
                workers = int(self.kwargs["workers"])
                inventory_prefilter = bool(self.kwargs["inventory_prefilter"])
                inventory_output = self.kwargs.get("inventory_output")

                if inventory_prefilter:
                    report = analyze_stl_folder_for_feature_graphs(
                        input_dir=input_path,
                        output_json=output_json,
                        inventory_config=InventoryConfig(
                            recursive=recursive,
                            max_files=max_files,
                            workers=workers,
                        ),
                        graph_workers=workers,
                        inventory_output_json=inventory_output,
                        inventory_progress_callback=lambda done, total, path: self.progress.emit(
                            f"[inventory {done}/{total}] {Path(path).name}"
                        ),
                        graph_progress_callback=lambda done, total, path: self.progress.emit(
                            f"[graph {done}/{total}] {Path(path).name}"
                        ),
                    )
                else:
                    report = build_feature_graph_for_folder(
                        input_path,
                        output_json,
                        recursive=recursive,
                        max_files=max_files,
                        workers=workers,
                        progress_callback=lambda done, total, path: self.progress.emit(
                            f"[graph {done}/{total}] {Path(path).name}"
                        ),
                    )

                self.finished.emit(
                    {
                        "mode": self.mode,
                        "report": report,
                        "output_json": str(output_json),
                        "inventory_output": (
                            str(inventory_output) if inventory_output else None
                        ),
                    }
                )
                return

            if self.mode == "from_inventory":
                inventory_json = Path(self.kwargs["inventory_json"])
                output_json = Path(self.kwargs["output_json"])
                workers = int(self.kwargs["workers"])
                preview_dir = self.kwargs.get("preview_dir")

                report = build_feature_graphs_from_inventory(
                    inventory=inventory_json,
                    output_json=output_json,
                    workers=workers,
                    progress_callback=lambda done, total, path: self.progress.emit(
                        f"[graph {done}/{total}] {Path(path).name}"
                    ),
                )

                emitted_previews = []
                if preview_dir:
                    emitted_previews = _emit_graph_report_previews(report, preview_dir)

                self.finished.emit(
                    {
                        "mode": self.mode,
                        "report": report,
                        "output_json": str(output_json),
                        "preview_dir": str(preview_dir) if preview_dir else None,
                        "emitted_previews": emitted_previews,
                    }
                )
                return

            raise ValueError(f"Unsupported feature graph mode: {self.mode}")
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------


def _hsep():
    """Thin horizontal separator line."""
    line = QFrame()
    line.setObjectName("hsep")
    line.setFrameShape(QFrame.HLine)
    return line


def _label(text, role=""):
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    return lbl


def _btn(text, object_name="secondary", checkable=False, tooltip=""):
    b = QPushButton(text)
    b.setObjectName(object_name)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    return b


def _spinbox(default, decimals=3, lo=0.0, hi=9999.0, step=0.1, width=100):
    sb = QDoubleSpinBox()
    sb.setDecimals(decimals)
    sb.setRange(lo, hi)
    sb.setValue(default)
    sb.setSingleStep(step)
    sb.setFixedWidth(width)
    return sb


def _int_spinbox(default, lo=0, hi=999999999, step=1, width=100):
    sb = QSpinBox()
    sb.setRange(lo, hi)
    sb.setValue(default)
    sb.setSingleStep(step)
    sb.setFixedWidth(width)
    return sb


def _combo(items, width=132):
    combo = QComboBox()
    combo.addItems(list(items))
    combo.setFixedWidth(width)
    return combo


def _resolve_gui_workers(value: int) -> int:
    if value < 0:
        raise ValueError("Workers must be non-negative")
    if value == 0:
        return max(1, min(os.cpu_count() or 1, 32))
    return value


def _write_text_file(path_like: Union[str, Path], contents: str) -> Path:
    path = Path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def _emit_graph_report_previews(
    report: Dict[str, Any], preview_root_like: Union[str, Path]
) -> list[str]:
    preview_root = Path(preview_root_like)
    preview_root.mkdir(parents=True, exist_ok=True)
    emitted_paths: list[str] = []
    for graph in report.get("graphs", []):
        if graph.get("status") == "error":
            continue
        scad = emit_feature_graph_scad_preview(graph)
        if scad is None:
            continue
        source_file = str(graph.get("source_file", "graph.stl"))
        relative_source = Path(source_file)
        output_path = preview_root / relative_source.with_suffix(".preview.scad")
        _write_text_file(output_path, scad)
        emitted_paths.append(str(output_path))
    return emitted_paths


def _format_acceleration_report(report: Dict[str, Any]) -> str:
    lines = [
        "Acceleration Report",
        f"GPU detected: {report.get('gpu_detected')}",
        f"GPU compute ready: {report.get('gpu_compute_ready')}",
        f"GPU compute library: {report.get('gpu_compute_backend')}",
        f"Compute reason: {report.get('gpu_compute_reason')}",
    ]

    devices = report.get("devices", [])
    if devices:
        lines.append("")
        lines.append("Devices:")
        for device in devices:
            line = f"- {device.get('vendor', 'unknown')}: {device.get('name', 'unknown')}"
            memory_total = device.get("memory_total")
            if memory_total:
                line += f" ({memory_total})"
            lines.append(line)

    recommendations = report.get("recommendations", [])
    if recommendations:
        lines.append("")
        lines.append("Recommendations:")
        for recommendation in recommendations:
            lines.append(f"- {recommendation}")

    return "\n".join(lines)


def _format_json_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _load_scad_conversion_metadata(scad_file: str) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    path = Path(scad_file)
    if not path.exists():
        return metadata

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    if metadata:
                        break
                    continue
                if not line.startswith("//"):
                    break

                comment = line[2:].strip()
                if not comment or comment == "STL to SCAD Conversion" or ":" not in comment:
                    continue

                key, value = comment.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key:
                    metadata[key] = value
    except OSError:
        return {}

    confidence_text = metadata.get("recognition_confidence")
    if isinstance(confidence_text, str):
        try:
            metadata["recognition_confidence"] = float(confidence_text)
        except ValueError:
            pass

    diagnostics_text = metadata.get("recognition_diagnostics")
    if isinstance(diagnostics_text, str):
        try:
            metadata["recognition_diagnostics"] = json.loads(diagnostics_text)
        except json.JSONDecodeError:
            pass

    return metadata


def _format_recognition_diagnostics(metadata: Optional[Dict[str, Any]]) -> str:
    if not metadata:
        return "No recognition diagnostics available yet."

    lines = []
    requested = metadata.get("recognition_backend_requested")
    used = metadata.get("recognition_backend_used")
    primitive_type = metadata.get("recognized_primitive_type")
    confidence = metadata.get("recognition_confidence")
    fallback_reason = metadata.get("recognition_fallback_reason")
    attempted = metadata.get("recognition_attempted")

    if requested:
        lines.append(f"Requested backend: {requested}")
    if used:
        lines.append(f"Used backend: {used}")
    if attempted is not None:
        lines.append(f"Recognition attempted: {attempted}")
    if primitive_type:
        lines.append(f"Primitive type: {primitive_type}")
    if confidence is not None:
        if isinstance(confidence, (int, float)):
            lines.append(f"Confidence: {float(confidence):.3f}")
        else:
            lines.append(f"Confidence: {confidence}")
    if fallback_reason:
        lines.append(f"Fallback reason: {fallback_reason}")

    diagnostics = metadata.get("recognition_diagnostics")
    if diagnostics:
        lines.append("Diagnostics:")
        if isinstance(diagnostics, dict):
            lines.append(json.dumps(diagnostics, indent=2, sort_keys=True))
        else:
            lines.append(str(diagnostics))

    return "\n".join(lines) if lines else "No recognition diagnostics available."


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_stl_file: Optional[str] = None
        self.current_scad_file: Optional[str] = None
        self.verify_scad_file: Optional[str] = None
        self.batch_input_dir: Optional[str] = None
        self.batch_output_dir: Optional[str] = None
        self.inventory_input_dir: Optional[str] = None
        self.inventory_output_json: Optional[str] = None
        self.graph_source_path: Optional[str] = None
        self.graph_output_json: Optional[str] = None
        self.graph_inventory_output_json: Optional[str] = None
        self.graph_preview_target: Optional[str] = None
        self.debug_mode = False
        self.current_color = (0.8, 0.8, 0.8, 1.0)
        self.mesh_data: Optional[gl.MeshData] = None
        self.mesh_item: Optional[gl.GLMeshItem] = None
        self.worker: Optional[QThread] = None
        self._busy = False
        self._available_recognition_backends = tuple(get_available_recognition_backends())
        self._last_recognition_metadata: Dict[str, Any] = {}
        self.setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def setup_ui(self):
        self.setWindowTitle("STL2SCAD — Converter")
        self.setStyleSheet(APP_STYLESHEET)
        self.resize(1320, 860)
        self.setMinimumSize(1024, 700)

        # ── Status bar ──────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._status_label = QLabel("Load an STL file to begin.")
        self._status_label.setObjectName("metric")
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate by default
        self._progress.setFixedWidth(140)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        self._badge = QLabel()
        self._badge.setFixedWidth(80)
        self._badge.setAlignment(Qt.AlignCenter)

        self._status_bar.addWidget(self._status_label, 1)
        self._status_bar.addPermanentWidget(self._progress)
        self._status_bar.addPermanentWidget(self._badge)

        # ── 3-D viewport ─────────────────────────────────────────────
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor(PALETTE["bg"])
        self.gl_view.opts["distance"] = 100
        self.gl_view.opts["elevation"] = 20
        self.gl_view.opts["azimuth"] = 45
        self.gl_view.opts["fov"] = 45
        self.gl_view.opts["center"] = pg.Vector(0, 0, 0)
        self.gl_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._add_reference_items()

        # Debug preview image (hidden unless debug mode)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setVisible(False)
        self.image_label.setMinimumHeight(160)
        self.image_label.setMaximumHeight(200)
        self.image_label.setObjectName("file_display")

        # Viewport container with overlay buttons
        viewport_container = QWidget()
        viewport_container.setLayout(QVBoxLayout())
        viewport_container.layout().setContentsMargins(0, 0, 0, 0)
        viewport_container.layout().setSpacing(0)
        viewport_container.layout().addWidget(self.gl_view)
        viewport_container.layout().addWidget(self.image_label)

        # Overlay view controls (float over viewport)
        self._build_view_overlay(viewport_container)

        # ── Mesh stats bar ───────────────────────────────────────────
        self._mesh_stats = QLabel("No model loaded")
        self._mesh_stats.setObjectName("metric")
        self._mesh_stats.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._mesh_stats.setContentsMargins(8, 4, 8, 4)
        stats_bar = QFrame()
        stats_bar.setObjectName("hsep")
        stats_bar_layout = QHBoxLayout(stats_bar)
        stats_bar_layout.setContentsMargins(4, 2, 4, 2)
        stats_bar_layout.addWidget(self._mesh_stats)
        stats_bar.setMaximumHeight(28)
        stats_bar.setStyleSheet(
            f"QFrame {{ background: {PALETTE['panel']}; border-top: 1px solid {PALETTE['border']}; }}"
        )

        # ── Central layout (sidebar | viewport) ─────────────────────
        sidebar = self._build_sidebar()

        center_layout = QHBoxLayout()
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(sidebar)

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(viewport_container, 1)
        right_layout.addWidget(stats_bar)

        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        center_layout.addWidget(right_widget, 1)

        root = QWidget()
        root.setLayout(center_layout)
        self.setCentralWidget(root)

    def _build_view_overlay(self, parent):
        """Place small floating buttons on top-right corner of the viewport."""
        overlay = QWidget(parent)
        overlay.setObjectName("overlay_panel")
        overlay.setAttribute(Qt.WA_TranslucentBackground)
        overlay_layout = QHBoxLayout(overlay)
        overlay_layout.setContentsMargins(6, 6, 6, 6)
        overlay_layout.setSpacing(4)

        for label, slot in [
            ("⟳ Center", self.center_object),
            ("X", lambda: self.rotate_object("x")),
            ("Y", lambda: self.rotate_object("y")),
            ("Z", lambda: self.rotate_object("z")),
            ("Fit", self.fit_to_window),
            ("Color", self.select_color),
        ]:
            b = _btn(label, "overlay")
            b.setFixedHeight(26)
            b.clicked.connect(slot)
            overlay_layout.addWidget(b)

        overlay_layout.addStretch(1)
        overlay.setGeometry(0, 0, 600, 38)
        overlay.raise_()

        # Reposition overlay when parent resizes.
        # Must return None — lambdas with tuple expressions return a tuple,
        # which causes sipBadCatcherResult() in PyQt5.
        def _resize(e, o=overlay, p=parent):
            QMainWindow.resizeEvent(self, e)
            o.setGeometry(0, 0, e.size().width(), 38)
            o.raise_()

        parent.resizeEvent = _resize

    def _build_sidebar(self):
        """Build the left sidebar with workflow steps."""
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # App title
        title_widget = QWidget()
        title_widget.setStyleSheet(
            f"background-color: {PALETTE['panel_alt']}; border-bottom: 1px solid {PALETTE['border']};"
        )
        title_layout = QVBoxLayout(title_widget)
        title_layout.setContentsMargins(14, 12, 14, 12)
        title_layout.setSpacing(2)
        name_lbl = QLabel("STL2SCAD")
        name_lbl.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {PALETTE['accent']}; letter-spacing: 3px; border: none; background: transparent;"
        )
        sub_lbl = QLabel("STL → OpenSCAD Converter")
        sub_lbl.setStyleSheet(
            f"font-size: 9px; color: {PALETTE['text_dim']}; letter-spacing: 1px; border: none; background: transparent;"
        )
        title_layout.addWidget(name_lbl)
        title_layout.addWidget(sub_lbl)
        outer.addWidget(title_widget)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("sidebar")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── STEP 1: INPUT ──────────────────────────────────────────
        grp1 = self._section_group("01  INPUT")
        g1 = QVBoxLayout()
        g1.setSpacing(6)

        self._stl_path_label = QLabel("No file selected")
        self._stl_path_label.setObjectName("file_display")
        self._stl_path_label.setWordWrap(True)
        self._stl_path_label.setMinimumHeight(36)

        self._open_btn = _btn("Open STL File…", "primary")
        self._open_btn.clicked.connect(self.load_stl_file)

        g1.addWidget(self._open_btn)
        g1.addWidget(_label("Input file:", "metric"))
        g1.addWidget(self._stl_path_label)
        grp1.setLayout(g1)
        layout.addWidget(grp1)

        # ── STEP 2: CONVERT ────────────────────────────────────────
        grp2 = self._section_group("02  CONVERT")
        g2 = QVBoxLayout()
        g2.setSpacing(6)

        # Output file row
        out_row = QHBoxLayout()
        self._scad_path_label = QLabel("Auto (same directory)")
        self._scad_path_label.setObjectName("file_display")
        self._scad_path_label.setWordWrap(True)
        self._set_output_btn = _btn("…", "secondary", tooltip="Change output path")
        self._set_output_btn.setFixedWidth(28)
        self._set_output_btn.setEnabled(False)
        self._set_output_btn.clicked.connect(self.select_output_scad_file)
        out_row.addWidget(self._scad_path_label, 1)
        out_row.addWidget(self._set_output_btn)

        # Convert tolerance
        tol_row = QHBoxLayout()
        tol_row.addWidget(_label("Tolerance:", "metric"))
        tol_row.addStretch(1)
        self.convert_tol_spin = _spinbox(
            1e-6, decimals=9, lo=1e-9, hi=1.0, step=1e-6, width=110
        )
        tol_row.addWidget(self.convert_tol_spin)

        # Options
        self.parametric_check = QCheckBox("Primitive detection (parametric)")
        self.parametric_check.setToolTip("Detect cubes, cylinders and other primitives")
        self.parametric_check.toggled.connect(self._toggle_parametric_options)

        backend_row = QHBoxLayout()
        backend_row.addWidget(_label("Backend:", "metric"))
        backend_row.addStretch(1)
        self.recognition_backend_combo = _combo(SUPPORTED_RECOGNITION_BACKENDS, width=150)
        self.recognition_backend_combo.setCurrentText("native")
        self.recognition_backend_combo.setEnabled(False)
        self._update_recognition_backend_tooltip()
        backend_row.addWidget(self.recognition_backend_combo)

        compute_row = QHBoxLayout()
        compute_row.addWidget(_label("Compute:", "metric"))
        compute_row.addStretch(1)
        self.compute_backend_combo = _combo(("auto", "cpu", "gpu"), width=110)
        self.compute_backend_combo.setCurrentText("auto")
        compute_row.addWidget(self.compute_backend_combo)

        self.debug_check = QCheckBox("Debug mode")
        self.debug_check.toggled.connect(self._toggle_debug)

        self._convert_btn = _btn("Convert to SCAD", "primary")
        self._convert_btn.setEnabled(False)
        self._convert_btn.clicked.connect(self.convert_to_scad)

        g2.addWidget(_label("Output:", "metric"))
        g2.addLayout(out_row)
        g2.addLayout(tol_row)
        g2.addWidget(self.parametric_check)
        g2.addLayout(backend_row)
        g2.addLayout(compute_row)
        g2.addWidget(self.debug_check)
        g2.addWidget(self._convert_btn)
        grp2.setLayout(g2)
        layout.addWidget(grp2)

        # ── STEP 3: VERIFY ─────────────────────────────────────────
        grp3 = self._section_group("03  VERIFY")
        g3 = QVBoxLayout()
        g3.setSpacing(6)

        # Verification mode
        self.use_existing_check = QCheckBox("Use existing SCAD file")
        self.use_existing_check.setEnabled(False)
        self.use_existing_check.toggled.connect(self._toggle_use_existing)

        self._verify_scad_label = QLabel("—")
        self._verify_scad_label.setObjectName("file_display")
        self._select_verify_btn = _btn("Select SCAD…", "secondary")
        self._select_verify_btn.setEnabled(False)
        self._select_verify_btn.clicked.connect(self.select_verify_scad_file)

        # Tolerance grid
        tol_grid = QHBoxLayout()
        tol_grid.setSpacing(6)
        tol_grid.addWidget(_label("Vol %", "metric"))
        self.volume_tol_spin = _spinbox(1.0, width=68)
        tol_grid.addWidget(self.volume_tol_spin)
        tol_grid.addWidget(_label("Surf %", "metric"))
        self.area_tol_spin = _spinbox(2.0, width=68)
        tol_grid.addWidget(self.area_tol_spin)

        bbox_row = QHBoxLayout()
        bbox_row.addWidget(_label("BBox %", "metric"))
        self.bbox_tol_spin = _spinbox(0.5, width=68)
        bbox_row.addWidget(self.bbox_tol_spin)
        bbox_row.addStretch(1)

        # Report options
        self.visualize_check = QCheckBox("Generate visualizations")
        self.html_report_check = QCheckBox("Generate HTML report")

        seed_row = QHBoxLayout()
        self.sample_seed_check = QCheckBox("Deterministic sampling")
        self.sample_seed_check.setToolTip(
            "Use a fixed seed for reproducible Hausdorff and normal-deviation sampling"
        )
        self.sample_seed_check.toggled.connect(self._toggle_sample_seed)
        self.sample_seed_spin = _int_spinbox(123, width=110)
        self.sample_seed_spin.setEnabled(False)
        seed_row.addWidget(self.sample_seed_check)
        seed_row.addStretch(1)
        seed_row.addWidget(self.sample_seed_spin)

        self._verify_btn = _btn("Verify Conversion", "primary")
        self._verify_btn.setEnabled(False)
        self._verify_btn.clicked.connect(self.verify_current_model)

        g3.addWidget(self.use_existing_check)
        g3.addWidget(_label("Verify against:", "metric"))
        g3.addWidget(self._verify_scad_label)
        g3.addWidget(self._select_verify_btn)
        g3.addWidget(_hsep())
        g3.addWidget(_label("Tolerances:", "metric"))
        g3.addLayout(tol_grid)
        g3.addLayout(bbox_row)
        g3.addWidget(_hsep())
        g3.addLayout(seed_row)
        g3.addWidget(self.visualize_check)
        g3.addWidget(self.html_report_check)
        g3.addWidget(self._verify_btn)
        grp3.setLayout(g3)
        layout.addWidget(grp3)

        grp4 = self._section_group("04  BATCH")
        g4 = QVBoxLayout()
        g4.setSpacing(6)

        batch_in_row = QHBoxLayout()
        self._batch_input_label = QLabel("No input directory selected")
        self._batch_input_label.setObjectName("file_display")
        self._batch_input_label.setWordWrap(True)
        self._batch_input_btn = _btn("…", "secondary", tooltip="Select batch input")
        self._batch_input_btn.setFixedWidth(28)
        self._batch_input_btn.clicked.connect(self.select_batch_input_dir)
        batch_in_row.addWidget(self._batch_input_label, 1)
        batch_in_row.addWidget(self._batch_input_btn)

        batch_out_row = QHBoxLayout()
        self._batch_output_label = QLabel("No output directory selected")
        self._batch_output_label.setObjectName("file_display")
        self._batch_output_label.setWordWrap(True)
        self._batch_output_btn = _btn("…", "secondary", tooltip="Select batch output")
        self._batch_output_btn.setFixedWidth(28)
        self._batch_output_btn.clicked.connect(self.select_batch_output_dir)
        batch_out_row.addWidget(self._batch_output_label, 1)
        batch_out_row.addWidget(self._batch_output_btn)

        batch_note = _label(
            "Uses the current convert and verify settings above.", "metric"
        )
        self._batch_btn = _btn("Run Batch Convert + Verify", "primary")
        self._batch_btn.clicked.connect(self.run_batch_processing)

        g4.addWidget(_label("Input directory:", "metric"))
        g4.addLayout(batch_in_row)
        g4.addWidget(_label("Output directory:", "metric"))
        g4.addLayout(batch_out_row)
        g4.addWidget(batch_note)
        g4.addWidget(self._batch_btn)
        grp4.setLayout(g4)
        layout.addWidget(grp4)

        grp5 = self._section_group("05  FEATURE TOOLS")
        g5 = QVBoxLayout()
        g5.setSpacing(6)

        inventory_in_row = QHBoxLayout()
        self._inventory_input_label = QLabel("No inventory directory selected")
        self._inventory_input_label.setObjectName("file_display")
        self._inventory_input_label.setWordWrap(True)
        self._inventory_input_btn = _btn("…", "secondary", tooltip="Select inventory input")
        self._inventory_input_btn.setFixedWidth(28)
        self._inventory_input_btn.clicked.connect(self.select_inventory_input_dir)
        inventory_in_row.addWidget(self._inventory_input_label, 1)
        inventory_in_row.addWidget(self._inventory_input_btn)

        inventory_out_row = QHBoxLayout()
        self._inventory_output_label = QLabel("Auto: artifacts/feature_inventory.json")
        self._inventory_output_label.setObjectName("file_display")
        self._inventory_output_label.setWordWrap(True)
        self._inventory_output_btn = _btn("…", "secondary", tooltip="Select inventory output")
        self._inventory_output_btn.setFixedWidth(28)
        self._inventory_output_btn.clicked.connect(self.select_inventory_output_json)
        inventory_out_row.addWidget(self._inventory_output_label, 1)
        inventory_out_row.addWidget(self._inventory_output_btn)

        inventory_options_row = QHBoxLayout()
        inventory_options_row.addWidget(_label("Max files", "metric"))
        self.inventory_max_files_spin = _int_spinbox(0, lo=0, hi=999999, width=90)
        inventory_options_row.addWidget(self.inventory_max_files_spin)
        inventory_options_row.addStretch(1)
        inventory_options_row.addWidget(_label("Workers", "metric"))
        self.inventory_workers_spin = _int_spinbox(0, lo=0, hi=128, width=70)
        inventory_options_row.addWidget(self.inventory_workers_spin)

        self.inventory_recursive_check = QCheckBox("Recursive scan")
        self.inventory_recursive_check.setChecked(True)
        self._inventory_btn = _btn("Run Feature Inventory", "primary")
        self._inventory_btn.clicked.connect(self.run_feature_inventory)

        graph_mode_row = QHBoxLayout()
        graph_mode_row.addWidget(_label("Graph source:", "metric"))
        graph_mode_row.addStretch(1)
        self.graph_source_mode_combo = _combo(
            (
                "Loaded STL",
                "Selected file",
                "Selected folder",
                "Inventory JSON",
            ),
            width=150,
        )
        self.graph_source_mode_combo.currentTextChanged.connect(
            self._update_graph_mode_controls
        )
        graph_mode_row.addWidget(self.graph_source_mode_combo)

        graph_source_row = QHBoxLayout()
        self._graph_source_label = QLabel("Uses the currently loaded STL file")
        self._graph_source_label.setObjectName("file_display")
        self._graph_source_label.setWordWrap(True)
        self._graph_source_btn = _btn("…", "secondary", tooltip="Select graph source")
        self._graph_source_btn.setFixedWidth(28)
        self._graph_source_btn.clicked.connect(self.select_graph_source_path)
        graph_source_row.addWidget(self._graph_source_label, 1)
        graph_source_row.addWidget(self._graph_source_btn)

        graph_output_row = QHBoxLayout()
        self._graph_output_label = QLabel("Auto: artifacts/feature_graph.json")
        self._graph_output_label.setObjectName("file_display")
        self._graph_output_label.setWordWrap(True)
        self._graph_output_btn = _btn("…", "secondary", tooltip="Select graph JSON output")
        self._graph_output_btn.setFixedWidth(28)
        self._graph_output_btn.clicked.connect(self.select_graph_output_json)
        graph_output_row.addWidget(self._graph_output_label, 1)
        graph_output_row.addWidget(self._graph_output_btn)

        graph_preview_row = QHBoxLayout()
        self._graph_preview_label = QLabel("Optional preview target")
        self._graph_preview_label.setObjectName("file_display")
        self._graph_preview_label.setWordWrap(True)
        self._graph_preview_btn = _btn("…", "secondary", tooltip="Select preview output")
        self._graph_preview_btn.setFixedWidth(28)
        self._graph_preview_btn.clicked.connect(self.select_graph_preview_target)
        graph_preview_row.addWidget(self._graph_preview_label, 1)
        graph_preview_row.addWidget(self._graph_preview_btn)

        graph_inventory_row = QHBoxLayout()
        self._graph_inventory_output_label = QLabel("Optional inventory JSON output")
        self._graph_inventory_output_label.setObjectName("file_display")
        self._graph_inventory_output_label.setWordWrap(True)
        self._graph_inventory_output_btn = _btn(
            "…", "secondary", tooltip="Select graph inventory output"
        )
        self._graph_inventory_output_btn.setFixedWidth(28)
        self._graph_inventory_output_btn.clicked.connect(
            self.select_graph_inventory_output_json
        )
        graph_inventory_row.addWidget(self._graph_inventory_output_label, 1)
        graph_inventory_row.addWidget(self._graph_inventory_output_btn)

        graph_options_row = QHBoxLayout()
        graph_options_row.addWidget(_label("Max files", "metric"))
        self.graph_max_files_spin = _int_spinbox(0, lo=0, hi=999999, width=90)
        graph_options_row.addWidget(self.graph_max_files_spin)
        graph_options_row.addStretch(1)
        graph_options_row.addWidget(_label("Workers", "metric"))
        self.graph_workers_spin = _int_spinbox(0, lo=0, hi=128, width=70)
        graph_options_row.addWidget(self.graph_workers_spin)

        self.graph_recursive_check = QCheckBox("Recursive scan")
        self.graph_recursive_check.setChecked(True)
        self.graph_inventory_prefilter_check = QCheckBox(
            "Inventory prefilter for folder graphs"
        )
        self.graph_inventory_prefilter_check.toggled.connect(
            self._update_graph_mode_controls
        )
        self._graph_btn = _btn("Run Feature Graph", "primary")
        self._graph_btn.clicked.connect(self.run_feature_graph)

        g5.addWidget(_label("Inventory input:", "metric"))
        g5.addLayout(inventory_in_row)
        g5.addWidget(_label("Inventory JSON:", "metric"))
        g5.addLayout(inventory_out_row)
        g5.addLayout(inventory_options_row)
        g5.addWidget(self.inventory_recursive_check)
        g5.addWidget(self._inventory_btn)
        g5.addWidget(_hsep())
        g5.addLayout(graph_mode_row)
        g5.addWidget(_label("Graph source path:", "metric"))
        g5.addLayout(graph_source_row)
        g5.addWidget(_label("Graph JSON:", "metric"))
        g5.addLayout(graph_output_row)
        g5.addWidget(_label("Preview output:", "metric"))
        g5.addLayout(graph_preview_row)
        g5.addWidget(_label("Inventory output for graph:", "metric"))
        g5.addLayout(graph_inventory_row)
        g5.addLayout(graph_options_row)
        g5.addWidget(self.graph_recursive_check)
        g5.addWidget(self.graph_inventory_prefilter_check)
        g5.addWidget(self._graph_btn)
        grp5.setLayout(g5)
        layout.addWidget(grp5)

        grp6 = self._section_group("06  OUTPUT")
        g6 = QVBoxLayout()
        g6.setSpacing(6)
        self.workflow_output_view = QPlainTextEdit()
        self.workflow_output_view.setReadOnly(True)
        self.workflow_output_view.setMinimumHeight(180)
        self.workflow_output_view.setPlainText("Workflow output will appear here.")
        self.workflow_output_view.setStyleSheet(
            f"background-color: {PALETTE['bg']};"
            f"border: 1px solid {PALETTE['border']};"
            "border-radius: 2px;"
            f"color: {PALETTE['text']};"
            'font-family: "Consolas", "Courier New", monospace;'
            "font-size: 11px;"
        )
        g6.addWidget(self.workflow_output_view)
        grp6.setLayout(g6)
        layout.addWidget(grp6)

        grp7 = self._section_group("07  DIAGNOSTICS")
        g7 = QVBoxLayout()
        g7.setSpacing(6)

        diagnostics_label = _label("Recognition diagnostics:", "metric")
        self.recognition_diagnostics_view = QPlainTextEdit()
        self.recognition_diagnostics_view.setReadOnly(True)
        self.recognition_diagnostics_view.setMinimumHeight(160)
        self.recognition_diagnostics_view.setPlainText(
            "No recognition diagnostics available yet."
        )
        self.recognition_diagnostics_view.setStyleSheet(
            f"background-color: {PALETTE['bg']};"
            f"border: 1px solid {PALETTE['border']};"
            "border-radius: 2px;"
            f"color: {PALETTE['text']};"
            'font-family: "Consolas", "Courier New", monospace;'
            "font-size: 11px;"
        )

        g7.addWidget(diagnostics_label)
        g7.addWidget(self.recognition_diagnostics_view)
        grp7.setLayout(g7)
        layout.addWidget(grp7)

        grp8 = self._section_group("08  ENVIRONMENT")
        g8 = QVBoxLayout()
        g8.setSpacing(6)
        self._acceleration_btn = _btn("Refresh Acceleration Report", "primary")
        self._acceleration_btn.clicked.connect(self.refresh_acceleration_report)
        self.acceleration_report_view = QPlainTextEdit()
        self.acceleration_report_view.setReadOnly(True)
        self.acceleration_report_view.setMinimumHeight(160)
        self.acceleration_report_view.setStyleSheet(
            f"background-color: {PALETTE['bg']};"
            f"border: 1px solid {PALETTE['border']};"
            "border-radius: 2px;"
            f"color: {PALETTE['text']};"
            'font-family: "Consolas", "Courier New", monospace;'
            "font-size: 11px;"
        )
        g8.addWidget(self._acceleration_btn)
        g8.addWidget(self.acceleration_report_view)
        grp8.setLayout(g8)
        layout.addWidget(grp8)

        layout.addStretch(1)

        ver_lbl = QLabel("stl2scad")
        ver_lbl.setAlignment(Qt.AlignCenter)
        ver_lbl.setStyleSheet(
            f"color: {PALETTE['border']}; font-size: 9px; padding: 6px;"
        )
        layout.addWidget(ver_lbl)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._update_graph_mode_controls()
        self._update_action_button_state()
        self.refresh_acceleration_report()
        return sidebar

    @staticmethod
    def _section_group(title):
        g = QGroupBox(title)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        return g

    def _add_reference_items(self):
        xy_grid = gl.GLGridItem()
        xy_grid.setSize(x=200, y=200, z=1)
        xy_grid.setSpacing(x=20, y=20, z=20)
        xy_grid.setColor((0.22, 0.22, 0.32, 0.5))
        self.gl_view.addItem(xy_grid)

        xz_grid = gl.GLGridItem()
        xz_grid.setSize(x=200, z=200, y=1)
        xz_grid.setSpacing(x=20, z=20, y=20)
        xz_grid.rotate(90, 1, 0, 0)
        xz_grid.translate(0, -100, 100)
        xz_grid.setColor((0.22, 0.22, 0.32, 0.2))
        self.gl_view.addItem(xz_grid)

        yz_grid = gl.GLGridItem()
        yz_grid.setSize(y=200, z=200, x=1)
        yz_grid.setSpacing(y=20, z=20, x=20)
        yz_grid.rotate(90, 0, 1, 0)
        yz_grid.translate(-100, 0, 100)
        yz_grid.setColor((0.22, 0.22, 0.32, 0.2))
        self.gl_view.addItem(yz_grid)

        axis = gl.GLAxisItem(size=pg.Vector(20, 20, 20))
        self.gl_view.addItem(axis)

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _set_status(self, message, color=None):
        self._status_label.setText(message)
        if color:
            self._status_label.setStyleSheet(f"color: {color};")
        else:
            self._status_label.setStyleSheet(f"color: {PALETTE['text_dim']};")

    def _set_badge(self, text, color):
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f"background-color: {color}22; color: {color}; border: 1px solid {color}55;"
            f" border-radius: 2px; font-size: 10px; font-weight: bold; padding: 1px 4px;"
        )

    def _start_busy(self, message):
        self._busy = True
        self._progress.setVisible(True)
        self._set_status(message)
        self._set_badge("BUSY", PALETTE["warning"])
        for button in self._action_buttons():
            button.setEnabled(False)

    def _stop_busy(self):
        self._busy = False
        self._progress.setVisible(False)
        self._update_action_button_state()

    def _action_buttons(self):
        return (
            self._convert_btn,
            self._verify_btn,
            self._batch_btn,
            self._inventory_btn,
            self._graph_btn,
            self._acceleration_btn,
        )

    def _update_action_button_state(self):
        if self._busy:
            return
        has_stl = bool(self.current_stl_file)
        self._convert_btn.setEnabled(has_stl)
        self._verify_btn.setEnabled(has_stl)
        self._batch_btn.setEnabled(True)
        self._inventory_btn.setEnabled(True)
        self._graph_btn.setEnabled(True)
        self._acceleration_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _toggle_debug(self, checked):
        self.debug_mode = checked
        if not checked:
            self.image_label.clear()
            self.image_label.setVisible(False)

    def _toggle_parametric_options(self, checked):
        self.recognition_backend_combo.setEnabled(checked)
        if checked:
            backend = self.recognition_backend_combo.currentText()
            self._set_status(f"Parametric mode enabled ({backend} backend).")
        else:
            self._set_status("Parametric mode disabled; polyhedron output only.")

    def _toggle_sample_seed(self, checked):
        self.sample_seed_spin.setEnabled(checked)
        if checked:
            self._set_status(
                f"Deterministic verification sampling enabled (seed {self.sample_seed_spin.value()})."
            )

    def _update_recognition_backend_tooltip(self):
        available = ", ".join(self._available_recognition_backends)
        self.recognition_backend_combo.setToolTip(
            "Recognition backend for parametric conversion. "
            f"Available in this environment: {available}"
        )

    def _toggle_use_existing(self, checked):
        self._select_verify_btn.setEnabled(checked)
        mode = "existing SCAD" if checked else "regenerate from STL"
        self._set_status(f"Verification mode: {mode}")

    def _set_recognition_diagnostics(self, metadata: Optional[Dict[str, Any]]):
        self._last_recognition_metadata = dict(metadata or {})
        self.recognition_diagnostics_view.setPlainText(
            _format_recognition_diagnostics(self._last_recognition_metadata)
        )

    def _set_workflow_output(self, text: str):
        self.workflow_output_view.setPlainText(text)

    def _set_path_label(
        self, label: QLabel, path: Optional[str], placeholder: str
    ) -> None:
        text = os.path.basename(path) if path else placeholder
        label.setText(text)
        label.setToolTip(path or placeholder)

    def _update_graph_mode_controls(self):
        mode = self.graph_source_mode_combo.currentText()
        uses_path_picker = mode in {"Selected file", "Selected folder", "Inventory JSON"}
        is_folder_mode = mode == "Selected folder"
        is_inventory_mode = mode == "Inventory JSON"
        is_single_file_mode = mode in {"Loaded STL", "Selected file"}

        self._graph_source_btn.setEnabled(uses_path_picker)
        self.graph_recursive_check.setEnabled(is_folder_mode)
        self.graph_max_files_spin.setEnabled(is_folder_mode)
        self.graph_inventory_prefilter_check.setEnabled(is_folder_mode)
        self._graph_inventory_output_btn.setEnabled(is_folder_mode)
        self._graph_preview_btn.setEnabled(is_inventory_mode or is_single_file_mode)

        if mode == "Loaded STL":
            if self.current_stl_file:
                self._set_path_label(
                    self._graph_source_label,
                    self.current_stl_file,
                    "Uses the currently loaded STL file",
                )
            else:
                self._graph_source_label.setText("No STL loaded")
                self._graph_source_label.setToolTip("No STL loaded")
        elif not self.graph_source_path:
            placeholder = {
                "Selected file": "No STL file selected",
                "Selected folder": "No folder selected",
                "Inventory JSON": "No inventory JSON selected",
            }[mode]
            self._graph_source_label.setText(placeholder)
            self._graph_source_label.setToolTip(placeholder)

        if is_inventory_mode:
            self._graph_preview_label.setText("Optional preview directory")
            self._graph_preview_label.setToolTip("Optional preview directory")
            self._graph_inventory_output_btn.setEnabled(False)
        elif is_single_file_mode:
            if not self.graph_preview_target:
                self._graph_preview_label.setText("Optional SCAD preview file")
                self._graph_preview_label.setToolTip("Optional SCAD preview file")
            self._graph_inventory_output_btn.setEnabled(False)
        else:
            if not self.graph_preview_target:
                self._graph_preview_label.setText("Preview target not available here")
                self._graph_preview_label.setToolTip(
                    "Preview target not available here"
                )

    def refresh_acceleration_report(self):
        report = get_acceleration_report()
        self.acceleration_report_view.setPlainText(_format_acceleration_report(report))
        self._set_workflow_output(_format_json_payload(report))
        self._set_status("Acceleration report refreshed.")
        self._set_badge("INFO", PALETTE["accent"])

    def select_batch_input_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Batch Input Directory", ""
        )
        if not path:
            return
        self.batch_input_dir = path
        self._set_path_label(
            self._batch_input_label, path, "No input directory selected"
        )
        if self.batch_output_dir is None:
            default_output = str(Path(path) / "batch_output")
            self.batch_output_dir = default_output
            self._set_path_label(
                self._batch_output_label, default_output, "No output directory selected"
            )

    def select_batch_output_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Batch Output Directory", ""
        )
        if not path:
            return
        self.batch_output_dir = path
        self._set_path_label(
            self._batch_output_label, path, "No output directory selected"
        )

    def select_inventory_input_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Inventory Input Directory", ""
        )
        if not path:
            return
        self.inventory_input_dir = path
        self._set_path_label(
            self._inventory_input_label, path, "No inventory directory selected"
        )
        if self.inventory_output_json is None:
            self.inventory_output_json = str(Path(path) / "feature_inventory.json")
            self._set_path_label(
                self._inventory_output_label,
                self.inventory_output_json,
                "Auto: artifacts/feature_inventory.json",
            )

    def select_inventory_output_json(self):
        initial = self.inventory_output_json or str(
            Path.cwd() / "artifacts" / "feature_inventory.json"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select Inventory JSON Output",
            initial,
            "JSON Files (*.json)",
        )
        if not path:
            return
        self.inventory_output_json = path
        self._set_path_label(
            self._inventory_output_label,
            path,
            "Auto: artifacts/feature_inventory.json",
        )

    def select_graph_source_path(self):
        mode = self.graph_source_mode_combo.currentText()
        if mode == "Selected file":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select STL File", "", "STL Files (*.stl)"
            )
        elif mode == "Selected folder":
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select Graph Input Directory", ""
            )
        elif mode == "Inventory JSON":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select Inventory JSON", "", "JSON Files (*.json)"
            )
        else:
            return

        if not path:
            return

        self.graph_source_path = path
        self._set_path_label(
            self._graph_source_label, path, "No graph source selected"
        )

    def select_graph_output_json(self):
        initial = self.graph_output_json or str(
            Path.cwd() / "artifacts" / "feature_graph.json"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select Feature Graph JSON Output",
            initial,
            "JSON Files (*.json)",
        )
        if not path:
            return
        self.graph_output_json = path
        self._set_path_label(
            self._graph_output_label, path, "Auto: artifacts/feature_graph.json"
        )

    def select_graph_inventory_output_json(self):
        initial = self.graph_inventory_output_json or str(
            Path.cwd() / "artifacts" / "feature_inventory_for_graph.json"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select Inventory Output For Graph",
            initial,
            "JSON Files (*.json)",
        )
        if not path:
            return
        self.graph_inventory_output_json = path
        self._set_path_label(
            self._graph_inventory_output_label,
            path,
            "Optional inventory JSON output",
        )

    def select_graph_preview_target(self):
        mode = self.graph_source_mode_combo.currentText()
        if mode == "Inventory JSON":
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select Preview Output Directory", ""
            )
        elif mode in {"Loaded STL", "Selected file"}:
            initial = self.graph_preview_target or str(
                Path.cwd() / "artifacts" / "feature_graph_preview.scad"
            )
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Select SCAD Preview Output",
                initial,
                "SCAD Files (*.scad)",
            )
        else:
            path = ""

        if not path:
            return
        self.graph_preview_target = path
        self._set_path_label(
            self._graph_preview_label, path, "Optional preview target"
        )

    def _connect_worker(self, worker: QThread, finished_slot, error_slot):
        self.worker = worker
        worker.progress.connect(self.update_status)
        worker.finished.connect(finished_slot)
        worker.error.connect(error_slot)

    def run_batch_processing(self):
        if not self.batch_input_dir:
            self.select_batch_input_dir()
        if not self.batch_input_dir:
            return
        if not self.batch_output_dir:
            self.select_batch_output_dir()
        if not self.batch_output_dir:
            return

        tolerance = {
            "volume": float(self.volume_tol_spin.value()),
            "surface_area": float(self.area_tol_spin.value()),
            "bounding_box": float(self.bbox_tol_spin.value()),
        }
        sample_seed = (
            int(self.sample_seed_spin.value())
            if self.sample_seed_check.isChecked()
            else None
        )
        worker = BatchWorker(
            self.batch_input_dir,
            self.batch_output_dir,
            tolerance=tolerance,
            html_report=self.html_report_check.isChecked(),
            parametric=self.parametric_check.isChecked(),
            recognition_backend=self.recognition_backend_combo.currentText(),
            compute_backend=self.compute_backend_combo.currentText(),
            sample_seed=sample_seed,
        )
        self._connect_worker(worker, self.batch_finished, self.batch_error)
        self._start_busy("Running batch convert + verify…")
        worker.start()

    def run_feature_inventory(self):
        if not self.inventory_input_dir:
            self.select_inventory_input_dir()
        if not self.inventory_input_dir:
            return
        if not self.inventory_output_json:
            self.inventory_output_json = str(
                Path(self.inventory_input_dir) / "feature_inventory.json"
            )
            self._set_path_label(
                self._inventory_output_label,
                self.inventory_output_json,
                "Auto: artifacts/feature_inventory.json",
            )

        worker = FeatureInventoryWorker(
            input_dir=self.inventory_input_dir,
            output_json=self.inventory_output_json,
            recursive=self.inventory_recursive_check.isChecked(),
            max_files=(
                int(self.inventory_max_files_spin.value())
                if self.inventory_max_files_spin.value() > 0
                else None
            ),
            workers=_resolve_gui_workers(int(self.inventory_workers_spin.value())),
        )
        self._connect_worker(
            worker, self.feature_inventory_finished, self.feature_inventory_error
        )
        self._start_busy("Running feature inventory…")
        worker.start()

    def run_feature_graph(self):
        mode = self.graph_source_mode_combo.currentText()
        workers = _resolve_gui_workers(int(self.graph_workers_spin.value()))
        max_files = (
            int(self.graph_max_files_spin.value())
            if self.graph_max_files_spin.value() > 0
            else None
        )

        if mode == "Loaded STL":
            if not self.current_stl_file:
                QtWidgets.QMessageBox.warning(
                    self, "Feature Graph", "Load an STL file first."
                )
                return
            source_path = self.current_stl_file
            output_json = self.graph_output_json or str(
                Path(source_path).with_suffix(".feature_graph.json")
            )
            worker = FeatureGraphWorker(
                "single_file",
                input_path=source_path,
                output_json=output_json,
                preview_path=self.graph_preview_target,
            )
        elif mode == "Selected file":
            if not self.graph_source_path:
                self.select_graph_source_path()
            if not self.graph_source_path:
                return
            output_json = self.graph_output_json or str(
                Path(self.graph_source_path).with_suffix(".feature_graph.json")
            )
            worker = FeatureGraphWorker(
                "single_file",
                input_path=self.graph_source_path,
                output_json=output_json,
                preview_path=self.graph_preview_target,
            )
        elif mode == "Selected folder":
            if not self.graph_source_path:
                self.select_graph_source_path()
            if not self.graph_source_path:
                return
            output_json = self.graph_output_json or str(
                Path(self.graph_source_path) / "feature_graph.json"
            )
            inventory_output = None
            if self.graph_inventory_prefilter_check.isChecked():
                inventory_output = self.graph_inventory_output_json or str(
                    Path(self.graph_source_path) / "feature_inventory_for_graph.json"
                )
                if self.graph_inventory_output_json is None:
                    self.graph_inventory_output_json = inventory_output
                    self._set_path_label(
                        self._graph_inventory_output_label,
                        inventory_output,
                        "Optional inventory JSON output",
                    )
            worker = FeatureGraphWorker(
                "folder",
                input_path=self.graph_source_path,
                output_json=output_json,
                recursive=self.graph_recursive_check.isChecked(),
                max_files=max_files,
                workers=workers,
                inventory_prefilter=self.graph_inventory_prefilter_check.isChecked(),
                inventory_output=inventory_output,
            )
        else:
            if not self.graph_source_path:
                self.select_graph_source_path()
            if not self.graph_source_path:
                return
            output_json = self.graph_output_json or str(
                Path(self.graph_source_path).with_name("feature_graph_from_inventory.json")
            )
            worker = FeatureGraphWorker(
                "from_inventory",
                inventory_json=self.graph_source_path,
                output_json=output_json,
                workers=workers,
                preview_dir=self.graph_preview_target,
            )

        self._connect_worker(worker, self.feature_graph_finished, self.feature_graph_error)
        self._start_busy("Running feature graph workflow…")
        worker.start()

    def load_stl_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open STL File", "", "STL Files (*.stl)"
        )
        if not file_path:
            return

        self.current_stl_file = file_path
        self.current_scad_file = os.path.splitext(file_path)[0] + ".scad"
        self.verify_scad_file = None

        # Enable controls
        self._set_output_btn.setEnabled(True)
        self.use_existing_check.setEnabled(True)
        self.use_existing_check.setChecked(False)
        self._select_verify_btn.setEnabled(False)
        self.image_label.setVisible(False)
        self.image_label.clear()
        self._set_recognition_diagnostics({})
        self._update_action_button_state()

        # Update labels
        self._stl_path_label.setText(os.path.basename(file_path))
        self._stl_path_label.setToolTip(file_path)
        self._scad_path_label.setText(os.path.basename(self.current_scad_file))
        self._scad_path_label.setToolTip(self.current_scad_file)
        self._verify_scad_label.setText(os.path.basename(self.current_scad_file))
        self._verify_scad_label.setToolTip(self.current_scad_file)
        self._update_graph_mode_controls()

        # Clear viewport
        self.gl_view.clear()
        self._add_reference_items()
        self.mesh_data = None
        self.mesh_item = None

        try:
            your_mesh = mesh.Mesh.from_file(file_path)
            vertices = np.concatenate(your_mesh.vectors)
            faces = np.arange(len(vertices)).reshape(-1, 3)
            self.mesh_data = gl.MeshData(vertexes=vertices, faces=faces)
            self.mesh_item = gl.GLMeshItem(
                meshdata=self.mesh_data,
                color=self.current_color,
                smooth=True,
                shader="balloon",
                drawFaces=True,
                drawEdges=False,
                glOptions="opaque",
            )
            self.gl_view.addItem(self.mesh_item)

            min_vals = vertices.min(axis=0)
            max_vals = vertices.max(axis=0)
            size = float(np.max(max_vals - min_vals))
            self._mesh_stats.setText(
                f"  {os.path.basename(file_path)}  ·  "
                f"{len(vertices):,} vertices  ·  {len(faces):,} faces  ·  "
                f"size {size:.2f}"
            )
            self._set_status(f"Loaded: {os.path.basename(file_path)}")
            self._set_badge("READY", PALETTE["success"])
        except Exception as exc:
            msg = f"Error loading STL: {exc}"
            self._set_status(msg, PALETTE["error"])
            self._set_badge("ERROR", PALETTE["error"])
            QtWidgets.QMessageBox.critical(self, "Loading Error", str(exc))
            return

        self.center_object()
        self.fit_to_window()

    def convert_to_scad(self):
        if not self.current_stl_file:
            return
        output_file = self.current_scad_file or (
            os.path.splitext(self.current_stl_file)[0] + ".scad"
        )
        self.current_scad_file = output_file

        self.worker = ConversionWorker(
            self.current_stl_file,
            output_file,
            tolerance=float(self.convert_tol_spin.value()),
            debug=self.debug_mode,
            parametric=self.parametric_check.isChecked(),
            recognition_backend=self.recognition_backend_combo.currentText(),
            compute_backend=self.compute_backend_combo.currentText(),
        )
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.error.connect(self.conversion_error)
        self._start_busy("Converting STL → SCAD…")
        self.worker.start()

    def verify_current_model(self):
        if not self.current_stl_file:
            return
        if not self.current_scad_file:
            self.current_scad_file = (
                os.path.splitext(self.current_stl_file)[0] + ".scad"
            )

        use_existing = self.use_existing_check.isChecked()
        scad_file = self.current_scad_file
        if use_existing:
            scad_file = self.verify_scad_file or self.current_scad_file
            if not scad_file or not os.path.exists(scad_file):
                file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self,
                    "Select SCAD File",
                    os.path.dirname(self.current_stl_file),
                    "SCAD Files (*.scad)",
                )
                if not file_path:
                    self._set_status("Verification canceled: no SCAD file selected.")
                    return
                self.verify_scad_file = file_path
                scad_file = file_path

        tolerance = {
            "volume": float(self.volume_tol_spin.value()),
            "surface_area": float(self.area_tol_spin.value()),
            "bounding_box": float(self.bbox_tol_spin.value()),
        }
        visualize = (
            self.visualize_check.isChecked() or self.html_report_check.isChecked()
        )

        self.worker = VerificationWorker(
            self.current_stl_file,
            scad_file,
            tolerance=tolerance,
            conversion_tolerance=float(self.convert_tol_spin.value()),
            parametric=self.parametric_check.isChecked(),
            recognition_backend=self.recognition_backend_combo.currentText(),
            compute_backend=self.compute_backend_combo.currentText(),
            regenerate_scad=not use_existing,
            visualize=visualize,
            html_report=self.html_report_check.isChecked(),
            sample_seed=(
                int(self.sample_seed_spin.value())
                if self.sample_seed_check.isChecked()
                else None
            ),
        )
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.verification_finished)
        self.worker.error.connect(self.verification_error)
        self._start_busy("Verifying conversion…")
        self.worker.start()

    def select_output_scad_file(self):
        if not self.current_stl_file:
            return
        initial = self.current_scad_file or (
            os.path.splitext(self.current_stl_file)[0] + ".scad"
        )
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select Output SCAD File", initial, "SCAD Files (*.scad)"
        )
        if not file_path:
            return
        self.current_scad_file = file_path
        self._scad_path_label.setText(os.path.basename(file_path))
        self._scad_path_label.setToolTip(file_path)
        self._set_status(f"Output SCAD: {file_path}")

    def select_verify_scad_file(self):
        if not self.current_stl_file:
            return
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select SCAD for Verification",
            os.path.dirname(self.current_stl_file),
            "SCAD Files (*.scad)",
        )
        if not file_path:
            return
        self.verify_scad_file = file_path
        self._verify_scad_label.setText(os.path.basename(file_path))
        self._verify_scad_label.setToolTip(file_path)
        self._set_status(f"Verify SCAD: {file_path}")

    # ------------------------------------------------------------------
    # Worker callbacks
    # ------------------------------------------------------------------

    def update_status(self, message):
        self._set_status(message)

    def conversion_finished(self, stats: ConversionStats):
        self._stop_busy()
        reduction = 100 * (1 - stats.deduplicated_vertices / stats.original_vertices)
        recognition_metadata = {}
        if self.current_scad_file:
            recognition_metadata = _load_scad_conversion_metadata(self.current_scad_file)
        self._set_recognition_diagnostics(recognition_metadata)
        self._set_status(
            f"Converted  ·  {stats.deduplicated_vertices:,} vertices ({reduction:.1f}% reduction)  ·  "
            f"{stats.faces:,} faces  ·  → {self.current_scad_file}",
            PALETTE["success"],
        )
        self._set_badge("OK", PALETTE["success"])

        if self.debug_mode and self.current_scad_file:
            scad_base = os.path.splitext(self.current_scad_file)[0]
            png_file = f"{scad_base}_preview.png"
            if os.path.exists(png_file):
                pixmap = QPixmap(png_file)
                self.image_label.setVisible(True)
                self.image_label.setPixmap(
                    pixmap.scaled(
                        self.image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def conversion_error(self, error_message):
        self._stop_busy()
        self._set_status(f"Conversion failed: {error_message}", PALETTE["error"])
        self._set_badge("FAIL", PALETTE["error"])
        QtWidgets.QMessageBox.critical(self, "Conversion Error", error_message)

    def verification_finished(self, payload: Dict[str, Any]):
        self._stop_busy()
        result = payload["result"]
        report_file = payload["report_file"]
        html_file = payload.get("html_file")
        recognition_metadata = dict(result.report.get("conversion_metadata") or {})
        if not recognition_metadata and payload.get("scad_file"):
            recognition_metadata = _load_scad_conversion_metadata(payload["scad_file"])
        self._set_recognition_diagnostics(recognition_metadata)
        passed = result.passed
        color = PALETTE["success"] if passed else PALETTE["error"]
        badge = "PASS" if passed else "FAIL"

        details = [
            f"Verification {'PASSED' if passed else 'FAILED'}",
            f"Report: {report_file}",
        ]
        if html_file:
            details.append(f"HTML: {html_file}")

        self._set_status("  ·  ".join(details), color)
        self._set_badge(badge, color)

        QtWidgets.QMessageBox.information(
            self, "Verification Complete", "\n".join(details)
        )

    def verification_error(self, error_message):
        self._stop_busy()
        self._set_status(f"Verification failed: {error_message}", PALETTE["error"])
        self._set_badge("FAIL", PALETTE["error"])
        QtWidgets.QMessageBox.critical(self, "Verification Error", error_message)

    def batch_finished(self, payload: Dict[str, Any]):
        self._stop_busy()
        summary = payload["summary"]
        summary_file = payload["summary_file"]
        self._set_workflow_output(_format_json_payload(summary))
        passed = summary["failed"] == 0
        color = PALETTE["success"] if passed else PALETTE["warning"]
        badge = "PASS" if passed else "WARN"
        self._set_status(
            (
                f"Batch complete  ·  {summary['passed']} passed  ·  "
                f"{summary['failed']} failed  ·  Summary: {summary_file}"
            ),
            color,
        )
        self._set_badge(badge, color)
        QtWidgets.QMessageBox.information(
            self,
            "Batch Complete",
            (
                f"Passed: {summary['passed']}\n"
                f"Failed: {summary['failed']}\n"
                f"Summary: {summary_file}"
            ),
        )

    def batch_error(self, error_message: str):
        self._stop_busy()
        self._set_status(f"Batch failed: {error_message}", PALETTE["error"])
        self._set_badge("FAIL", PALETTE["error"])
        QtWidgets.QMessageBox.critical(self, "Batch Error", error_message)

    def feature_inventory_finished(self, payload: Dict[str, Any]):
        self._stop_busy()
        report = payload["report"]
        self._set_workflow_output(_format_json_payload(report))
        summary = report["summary"]
        self._set_status(
            (
                f"Feature inventory written  ·  {summary['file_count']} files  ·  "
                f"OK {summary['ok_count']}  ·  Errors {summary['error_count']}  ·  "
                f"{payload['output_json']}"
            ),
            PALETTE["success"],
        )
        self._set_badge("OK", PALETTE["success"])

    def feature_inventory_error(self, error_message: str):
        self._stop_busy()
        self._set_status(f"Feature inventory failed: {error_message}", PALETTE["error"])
        self._set_badge("FAIL", PALETTE["error"])
        QtWidgets.QMessageBox.critical(self, "Feature Inventory Error", error_message)

    def feature_graph_finished(self, payload: Dict[str, Any]):
        self._stop_busy()
        report = payload["report"]
        self._set_workflow_output(_format_json_payload(report))
        mode = payload["mode"]
        if mode == "single_file":
            preview_message = ""
            if payload.get("preview_path"):
                preview_message = f"  ·  Preview: {payload['preview_path']}"
            self._set_status(
                f"Feature graph written  ·  {payload['output_json']}{preview_message}",
                PALETTE["success"],
            )
        elif mode == "folder":
            selection = report.get("selection")
            if selection:
                self._set_status(
                    (
                        f"Prefiltered feature graph written  ·  "
                        f"Mechanical candidates {selection['mechanical_candidate_count']}  ·  "
                        f"{payload['output_json']}"
                    ),
                    PALETTE["success"],
                )
            else:
                self._set_status(
                    (
                        f"Feature graph written  ·  "
                        f"Files {report['summary']['file_count']}  ·  {payload['output_json']}"
                    ),
                    PALETTE["success"],
                )
        else:
            self._set_status(
                (
                    f"Feature graph from inventory written  ·  "
                    f"Processed {report['selection']['mechanical_candidate_count']}  ·  "
                    f"{payload['output_json']}"
                ),
                PALETTE["success"],
            )
        self._set_badge("OK", PALETTE["success"])

    def feature_graph_error(self, error_message: str):
        self._stop_busy()
        self._set_status(f"Feature graph failed: {error_message}", PALETTE["error"])
        self._set_badge("FAIL", PALETTE["error"])
        QtWidgets.QMessageBox.critical(self, "Feature Graph Error", error_message)

    # ------------------------------------------------------------------
    # 3-D view controls
    # ------------------------------------------------------------------

    def center_object(self):
        if self.mesh_data is None:
            return
        vertices = self.mesh_data.vertexes()
        center = vertices.mean(axis=0)
        size = float(np.max(vertices.max(axis=0) - vertices.min(axis=0)))
        self.gl_view.opts["center"] = pg.Vector(center[0], center[1], center[2])
        self.gl_view.setCameraPosition(
            distance=max(size * 2, 1.0), elevation=45, azimuth=45
        )
        self.gl_view.update()

    def rotate_object(self, axis):
        if self.mesh_data is None:
            return
        vertices = self.mesh_data.vertexes()
        center = vertices.mean(axis=0)
        size = float(np.max(vertices.max(axis=0) - vertices.min(axis=0)))
        distance = max(size * 2, 1.0)
        self.gl_view.opts["center"] = pg.Vector(center[0], center[1], center[2])
        if axis == "x":
            self.gl_view.setCameraPosition(distance=distance, elevation=0, azimuth=90)
        elif axis == "y":
            self.gl_view.setCameraPosition(distance=distance, elevation=0, azimuth=0)
        elif axis == "z":
            self.gl_view.setCameraPosition(distance=distance, elevation=90, azimuth=0)
        self.gl_view.update()

    def fit_to_window(self):
        if self.mesh_data is None:
            return
        vertices = self.mesh_data.vertexes()
        min_vals = vertices.min(axis=0)
        max_vals = vertices.max(axis=0)
        size = float(np.max(max_vals - min_vals))
        center = (max_vals + min_vals) / 2
        self.gl_view.opts["center"] = pg.Vector(center[0], center[1], center[2])
        self.gl_view.setCameraPosition(distance=max(size * 2, 1.0))
        self.gl_view.update()

    def select_color(self):
        if self.mesh_data is None:
            return
        color = QtWidgets.QColorDialog.getColor(initial=QColor(180, 180, 180))
        if not color.isValid():
            return
        self.current_color = color.getRgbF()
        if self.mesh_item is not None:
            self.gl_view.removeItem(self.mesh_item)
        self.mesh_item = gl.GLMeshItem(
            meshdata=self.mesh_data,
            color=self.current_color,
            smooth=True,
            shader="balloon",
            drawFaces=True,
            drawEdges=False,
            glOptions="opaque",
        )
        self.gl_view.addItem(self.mesh_item)
