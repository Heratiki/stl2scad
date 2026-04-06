"""
Main window implementation for the STL to OpenSCAD converter GUI.
"""

import os
from typing import Any, Dict, Optional

import numpy as np
from PyQt5 import QtWidgets
from PyQt5.QtCore import QThread, Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer
from PyQt5.QtGui import QColor, QPixmap, QFont, QPalette, QIcon
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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

from stl2scad.core.converter import ConversionStats, stl2scad
from stl2scad.core.verification import (
    generate_comparison_visualization,
    generate_verification_report_html,
    verify_conversion,
)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
PALETTE = {
    "bg":        "#16161d",
    "panel":     "#1f1f2b",
    "panel_alt": "#252534",
    "border":    "#35354a",
    "accent":    "#e8682a",
    "accent_dk": "#c0531f",
    "text":      "#d8d8e8",
    "text_dim":  "#888899",
    "success":   "#4ec98a",
    "warning":   "#f0b84a",
    "error":     "#e05555",
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
QDoubleSpinBox {{
    background-color: {PALETTE["bg"]};
    color: {PALETTE["text"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 2px;
    padding: 2px 4px;
    font-family: "Consolas", monospace;
    font-size: 11px;
}}
QDoubleSpinBox:focus {{
    border-color: {PALETTE["accent"]};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {PALETTE["panel_alt"]};
    border: none;
    width: 14px;
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

    def __init__(self, input_file, output_file, tolerance=1e-6, debug=False, parametric=False):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.tolerance = tolerance
        self.debug = debug
        self.parametric = parametric

    def run(self):
        try:
            self.progress.emit("Converting STL to SCAD…")
            stats = stl2scad(self.input_file, self.output_file, self.tolerance, self.debug, self.parametric)
            self.finished.emit(stats)
        except Exception as exc:
            self.error.emit(str(exc))


class VerificationWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, stl_file, scad_file, tolerance, conversion_tolerance, parametric,
                 regenerate_scad, visualize, html_report):
        super().__init__()
        self.stl_file = stl_file
        self.scad_file = scad_file
        self.tolerance = tolerance
        self.conversion_tolerance = conversion_tolerance
        self.parametric = parametric
        self.regenerate_scad = regenerate_scad
        self.visualize = visualize
        self.html_report = html_report

    def run(self):
        try:
            self.progress.emit("Preparing SCAD file for verification…")
            if self.regenerate_scad:
                stl2scad(self.stl_file, self.scad_file,
                         tolerance=self.conversion_tolerance, parametric=self.parametric)
            elif not os.path.exists(self.scad_file):
                raise FileNotFoundError(f"SCAD file not found: {self.scad_file}")

            self.progress.emit("Running geometric verification…")
            result = verify_conversion(self.stl_file, self.scad_file, self.tolerance, debug=False)

            report_dir = os.path.dirname(self.scad_file) or os.path.dirname(self.stl_file)
            report_base = os.path.splitext(os.path.basename(self.stl_file))[0]
            report_file = os.path.join(report_dir, f"{report_base}_verification.json")
            result.save_report(report_file)

            visualizations: Dict[str, str] = {}
            html_file: Optional[str] = None
            vis_paths = {}

            if self.visualize or self.html_report:
                self.progress.emit("Generating visualization artifacts…")
                vis_dir = os.path.join(report_dir, f"{report_base}_visualizations")
                vis_paths = generate_comparison_visualization(self.stl_file, self.scad_file, vis_dir)
                visualizations = {k: str(v) for k, v in vis_paths.items()}

            if self.html_report:
                self.progress.emit("Generating HTML report…")
                html_file = os.path.join(report_dir, f"{report_base}_verification.html")
                generate_verification_report_html(vars(result), vis_paths, html_file)

            self.finished.emit({
                "result": result,
                "scad_file": self.scad_file,
                "report_file": report_file,
                "visualizations": visualizations,
                "html_file": html_file,
            })
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


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_stl_file: Optional[str] = None
        self.current_scad_file: Optional[str] = None
        self.verify_scad_file: Optional[str] = None
        self.debug_mode = False
        self.current_color = (0.8, 0.8, 0.8, 1.0)
        self.mesh_data: Optional[gl.MeshData] = None
        self.mesh_item: Optional[gl.GLMeshItem] = None
        self.worker: Optional[QThread] = None
        self._busy = False
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
        self._progress.setRange(0, 0)        # indeterminate by default
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
        stats_bar.setStyleSheet(f"QFrame {{ background: {PALETTE['panel']}; border-top: 1px solid {PALETTE['border']}; }}")

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
        title_widget.setStyleSheet(f"background-color: {PALETTE['panel_alt']}; border-bottom: 1px solid {PALETTE['border']};")
        title_layout = QVBoxLayout(title_widget)
        title_layout.setContentsMargins(14, 12, 14, 12)
        title_layout.setSpacing(2)
        name_lbl = QLabel("STL2SCAD")
        name_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {PALETTE['accent']}; letter-spacing: 3px; border: none; background: transparent;")
        sub_lbl = QLabel("STL → OpenSCAD Converter")
        sub_lbl.setStyleSheet(f"font-size: 9px; color: {PALETTE['text_dim']}; letter-spacing: 1px; border: none; background: transparent;")
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
        self.convert_tol_spin = _spinbox(1e-6, decimals=9, lo=1e-9, hi=1.0, step=1e-6, width=110)
        tol_row.addWidget(self.convert_tol_spin)

        # Options
        self.parametric_check = QCheckBox("Primitive detection (parametric)")
        self.parametric_check.setToolTip("Detect cubes, cylinders and other primitives")
        self.debug_check = QCheckBox("Debug mode")
        self.debug_check.toggled.connect(self._toggle_debug)

        self._convert_btn = _btn("Convert to SCAD", "primary")
        self._convert_btn.setEnabled(False)
        self._convert_btn.clicked.connect(self.convert_to_scad)

        g2.addWidget(_label("Output:", "metric"))
        g2.addLayout(out_row)
        g2.addLayout(tol_row)
        g2.addWidget(self.parametric_check)
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
        g3.addWidget(self.visualize_check)
        g3.addWidget(self.html_report_check)
        g3.addWidget(self._verify_btn)
        grp3.setLayout(g3)
        layout.addWidget(grp3)

        layout.addStretch(1)

        # Version label at bottom
        ver_lbl = QLabel("stl2scad")
        ver_lbl.setAlignment(Qt.AlignCenter)
        ver_lbl.setStyleSheet(f"color: {PALETTE['border']}; font-size: 9px; padding: 6px;")
        layout.addWidget(ver_lbl)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
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
        self._convert_btn.setEnabled(False)
        self._verify_btn.setEnabled(False)

    def _stop_busy(self):
        self._busy = False
        self._progress.setVisible(False)
        if self.current_stl_file:
            self._convert_btn.setEnabled(True)
            self._verify_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _toggle_debug(self, checked):
        self.debug_mode = checked
        if not checked:
            self.image_label.clear()
            self.image_label.setVisible(False)

    def _toggle_use_existing(self, checked):
        self._select_verify_btn.setEnabled(checked)
        mode = "existing SCAD" if checked else "regenerate from STL"
        self._set_status(f"Verification mode: {mode}")

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
        self._convert_btn.setEnabled(True)
        self._set_output_btn.setEnabled(True)
        self._verify_btn.setEnabled(True)
        self.use_existing_check.setEnabled(True)
        self.use_existing_check.setChecked(False)
        self._select_verify_btn.setEnabled(False)
        self.image_label.setVisible(False)
        self.image_label.clear()

        # Update labels
        self._stl_path_label.setText(os.path.basename(file_path))
        self._stl_path_label.setToolTip(file_path)
        self._scad_path_label.setText(os.path.basename(self.current_scad_file))
        self._scad_path_label.setToolTip(self.current_scad_file)
        self._verify_scad_label.setText(os.path.basename(self.current_scad_file))

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
        output_file = self.current_scad_file or (os.path.splitext(self.current_stl_file)[0] + ".scad")
        self.current_scad_file = output_file

        self.worker = ConversionWorker(
            self.current_stl_file, output_file,
            tolerance=float(self.convert_tol_spin.value()),
            debug=self.debug_mode,
            parametric=self.parametric_check.isChecked(),
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
            self.current_scad_file = os.path.splitext(self.current_stl_file)[0] + ".scad"

        use_existing = self.use_existing_check.isChecked()
        scad_file = self.current_scad_file
        if use_existing:
            scad_file = self.verify_scad_file or self.current_scad_file
            if not scad_file or not os.path.exists(scad_file):
                file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, "Select SCAD File", os.path.dirname(self.current_stl_file), "SCAD Files (*.scad)"
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
        visualize = self.visualize_check.isChecked() or self.html_report_check.isChecked()

        self.worker = VerificationWorker(
            self.current_stl_file, scad_file,
            tolerance=tolerance,
            conversion_tolerance=float(self.convert_tol_spin.value()),
            parametric=self.parametric_check.isChecked(),
            regenerate_scad=not use_existing,
            visualize=visualize,
            html_report=self.html_report_check.isChecked(),
        )
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.verification_finished)
        self.worker.error.connect(self.verification_error)
        self._start_busy("Verifying conversion…")
        self.worker.start()

    def select_output_scad_file(self):
        if not self.current_stl_file:
            return
        initial = self.current_scad_file or (os.path.splitext(self.current_stl_file)[0] + ".scad")
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
            self, "Select SCAD for Verification",
            os.path.dirname(self.current_stl_file), "SCAD Files (*.scad)"
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
                    pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
        passed = result.passed
        color = PALETTE["success"] if passed else PALETTE["error"]
        badge = "PASS" if passed else "FAIL"

        details = [f"Verification {'PASSED' if passed else 'FAILED'}", f"Report: {report_file}"]
        if html_file:
            details.append(f"HTML: {html_file}")

        self._set_status("  ·  ".join(details), color)
        self._set_badge(badge, color)

        QtWidgets.QMessageBox.information(self, "Verification Complete", "\n".join(details))

    def verification_error(self, error_message):
        self._stop_busy()
        self._set_status(f"Verification failed: {error_message}", PALETTE["error"])
        self._set_badge("FAIL", PALETTE["error"])
        QtWidgets.QMessageBox.critical(self, "Verification Error", error_message)

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
        self.gl_view.setCameraPosition(distance=max(size * 2, 1.0), elevation=45, azimuth=45)
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
