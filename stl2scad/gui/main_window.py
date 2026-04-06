"""
Main window implementation for the STL to OpenSCAD converter GUI.
"""

import os
from typing import Any, Dict, Optional

import numpy as np
from PyQt5 import QtWidgets
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
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


class ConversionWorker(QThread):
    """Worker thread for STL to OpenSCAD conversion."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        input_file: str,
        output_file: str,
        tolerance: float = 1e-6,
        debug: bool = False,
        parametric: bool = False,
    ) -> None:
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.tolerance = tolerance
        self.debug = debug
        self.parametric = parametric

    def run(self) -> None:
        try:
            self.progress.emit("Converting STL to SCAD...")
            stats = stl2scad(
                self.input_file,
                self.output_file,
                self.tolerance,
                self.debug,
                self.parametric,
            )
            self.finished.emit(stats)
        except Exception as exc:
            self.error.emit(str(exc))


class VerificationWorker(QThread):
    """Worker thread for STL/SCAD verification and optional report artifacts."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        stl_file: str,
        scad_file: str,
        tolerance: Dict[str, float],
        conversion_tolerance: float,
        parametric: bool,
        regenerate_scad: bool,
        visualize: bool,
        html_report: bool,
    ) -> None:
        super().__init__()
        self.stl_file = stl_file
        self.scad_file = scad_file
        self.tolerance = tolerance
        self.conversion_tolerance = conversion_tolerance
        self.parametric = parametric
        self.regenerate_scad = regenerate_scad
        self.visualize = visualize
        self.html_report = html_report

    def run(self) -> None:
        try:
            self.progress.emit("Preparing SCAD file for verification...")
            if self.regenerate_scad:
                stl2scad(
                    self.stl_file,
                    self.scad_file,
                    tolerance=self.conversion_tolerance,
                    parametric=self.parametric,
                )
            elif not os.path.exists(self.scad_file):
                raise FileNotFoundError(f"SCAD file not found: {self.scad_file}")

            self.progress.emit("Running geometric verification...")
            result = verify_conversion(self.stl_file, self.scad_file, self.tolerance, debug=False)

            report_dir = os.path.dirname(self.scad_file) or os.path.dirname(self.stl_file)
            report_base = os.path.splitext(os.path.basename(self.stl_file))[0]
            report_file = os.path.join(report_dir, f"{report_base}_verification.json")
            result.save_report(report_file)

            visualizations: Dict[str, str] = {}
            html_file: Optional[str] = None

            if self.visualize or self.html_report:
                self.progress.emit("Generating visualization artifacts...")
                vis_dir = os.path.join(report_dir, f"{report_base}_visualizations")
                vis_paths = generate_comparison_visualization(self.stl_file, self.scad_file, vis_dir)
                visualizations = {k: str(v) for k, v in vis_paths.items()}

            if self.html_report:
                self.progress.emit("Generating HTML report...")
                html_file = os.path.join(report_dir, f"{report_base}_verification.html")
                generate_verification_report_html(vars(result), vis_paths if (self.visualize or self.html_report) else {}, html_file)

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


class MainWindow(QMainWindow):
    """Main window for the STL to OpenSCAD converter application."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_stl_file: Optional[str] = None
        self.current_scad_file: Optional[str] = None
        self.verify_scad_file: Optional[str] = None
        self.debug_mode = False
        self.current_color = (0.8, 0.8, 0.8, 1.0)
        self.mesh_data: Optional[gl.MeshData] = None
        self.mesh_item: Optional[gl.GLMeshItem] = None
        self.worker: Optional[QThread] = None
        self.setup_ui()

    def setup_ui(self) -> None:
        """Initialize the user interface."""
        self.setWindowTitle("STL2SCAD")

        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor("w")
        self.gl_view.opts["distance"] = 100
        self.gl_view.opts["elevation"] = 20
        self.gl_view.opts["azimuth"] = 45
        self.gl_view.opts["fov"] = 45
        self.gl_view.opts["center"] = pg.Vector(0, 0, 0)
        self._add_reference_items()

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 220)

        self.toolbar = self.addToolBar("Tools")
        self.toolbar.setMovable(False)

        self.open_file_action = QtWidgets.QAction("Open STL File", self)
        self.open_file_action.triggered.connect(self.load_stl_file)
        self.toolbar.addAction(self.open_file_action)

        self.convert_action = QtWidgets.QAction("Convert to SCAD", self)
        self.convert_action.triggered.connect(self.convert_to_scad)
        self.convert_action.setEnabled(False)
        self.toolbar.addAction(self.convert_action)

        self.set_output_action = QtWidgets.QAction("Set SCAD Output", self)
        self.set_output_action.triggered.connect(self.select_output_scad_file)
        self.set_output_action.setEnabled(False)
        self.toolbar.addAction(self.set_output_action)

        self.verify_action = QtWidgets.QAction("Verify Conversion", self)
        self.verify_action.triggered.connect(self.verify_current_model)
        self.verify_action.setEnabled(False)
        self.toolbar.addAction(self.verify_action)

        self.use_existing_scad_action = QtWidgets.QAction("Use Existing SCAD", self, checkable=True)
        self.use_existing_scad_action.triggered.connect(self.toggle_use_existing_scad)
        self.use_existing_scad_action.setEnabled(False)
        self.toolbar.addAction(self.use_existing_scad_action)

        self.select_verify_scad_action = QtWidgets.QAction("Select Verify SCAD", self)
        self.select_verify_scad_action.triggered.connect(self.select_verify_scad_file)
        self.select_verify_scad_action.setEnabled(False)
        self.toolbar.addAction(self.select_verify_scad_action)

        self.toolbar.addSeparator()

        self.center_action = QtWidgets.QAction("Center", self)
        self.center_action.triggered.connect(self.center_object)
        self.toolbar.addAction(self.center_action)

        self.rotate_x_action = QtWidgets.QAction("Rotate X", self)
        self.rotate_x_action.triggered.connect(lambda: self.rotate_object("x"))
        self.toolbar.addAction(self.rotate_x_action)

        self.rotate_y_action = QtWidgets.QAction("Rotate Y", self)
        self.rotate_y_action.triggered.connect(lambda: self.rotate_object("y"))
        self.toolbar.addAction(self.rotate_y_action)

        self.rotate_z_action = QtWidgets.QAction("Rotate Z", self)
        self.rotate_z_action.triggered.connect(lambda: self.rotate_object("z"))
        self.toolbar.addAction(self.rotate_z_action)

        self.fit_action = QtWidgets.QAction("Fit", self)
        self.fit_action.triggered.connect(self.fit_to_window)
        self.toolbar.addAction(self.fit_action)

        self.color_action = QtWidgets.QAction("Select Color", self)
        self.color_action.triggered.connect(self.select_color)
        self.toolbar.addAction(self.color_action)

        self.toolbar.addSeparator()

        self.debug_action = QtWidgets.QAction("Debug", self, checkable=True)
        self.debug_action.triggered.connect(self.toggle_debug_mode)
        self.toolbar.addAction(self.debug_action)

        self.parametric_action = QtWidgets.QAction("Parametric", self, checkable=True)
        self.parametric_action.setToolTip("Enable primitive detection during conversion")
        self.toolbar.addAction(self.parametric_action)

        self.visualize_action = QtWidgets.QAction("Visualize", self, checkable=True)
        self.visualize_action.setToolTip("Generate verification visualization files")
        self.toolbar.addAction(self.visualize_action)

        self.html_report_action = QtWidgets.QAction("HTML Report", self, checkable=True)
        self.html_report_action.setToolTip("Generate verification HTML report")
        self.toolbar.addAction(self.html_report_action)

        layout = QVBoxLayout()
        self.gl_view.setMinimumSize(1000, 700)
        layout.addWidget(self.gl_view, stretch=8)
        layout.addWidget(self.image_label, stretch=1)

        tolerance_layout = QHBoxLayout()
        tolerance_layout.addWidget(QLabel("Convert Tol"))
        self.convert_tol_spin = self._make_conversion_tolerance_spinbox(1e-6)
        tolerance_layout.addWidget(self.convert_tol_spin)

        tolerance_layout.addSpacing(16)
        tolerance_layout.addWidget(QLabel("Verify Tol %:"))
        self.volume_tol_spin = self._make_tolerance_spinbox(1.0)
        self.area_tol_spin = self._make_tolerance_spinbox(2.0)
        self.bbox_tol_spin = self._make_tolerance_spinbox(0.5)
        tolerance_layout.addWidget(QLabel("Volume"))
        tolerance_layout.addWidget(self.volume_tol_spin)
        tolerance_layout.addWidget(QLabel("Surface"))
        tolerance_layout.addWidget(self.area_tol_spin)
        tolerance_layout.addWidget(QLabel("BBox"))
        tolerance_layout.addWidget(self.bbox_tol_spin)
        tolerance_layout.addStretch(1)
        layout.addLayout(tolerance_layout, stretch=0)

        info_layout = QHBoxLayout()
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignLeft)
        info_layout.addWidget(self.info_label)

        self.status_label = QLabel("Load an STL file to begin.")
        self.status_label.setAlignment(Qt.AlignRight)
        info_layout.addWidget(self.status_label)
        layout.addLayout(info_layout, stretch=0)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        self.resize(1200, 800)
        self.setMinimumSize(1024, 768)

    def _make_tolerance_spinbox(self, default: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(3)
        spinbox.setRange(0.0, 9999.0)
        spinbox.setValue(default)
        spinbox.setSingleStep(0.1)
        spinbox.setFixedWidth(90)
        return spinbox

    def _make_conversion_tolerance_spinbox(self, default: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(9)
        spinbox.setRange(1e-9, 1.0)
        spinbox.setValue(default)
        spinbox.setSingleStep(1e-6)
        spinbox.setFixedWidth(110)
        return spinbox

    def _add_reference_items(self) -> None:
        """Add static reference guides (grids + axis) to the GL view."""
        xy_grid = gl.GLGridItem()
        xy_grid.setSize(x=200, y=200, z=1)
        xy_grid.setSpacing(x=20, y=20, z=20)
        xy_grid.setColor((0.7, 0.7, 0.7, 0.4))
        self.gl_view.addItem(xy_grid)

        xz_grid = gl.GLGridItem()
        xz_grid.setSize(x=200, z=200, y=1)
        xz_grid.setSpacing(x=20, z=20, y=20)
        xz_grid.rotate(90, 1, 0, 0)
        xz_grid.translate(0, -100, 100)
        xz_grid.setColor((0.7, 0.7, 0.7, 0.2))
        self.gl_view.addItem(xz_grid)

        yz_grid = gl.GLGridItem()
        yz_grid.setSize(y=200, z=200, x=1)
        yz_grid.setSpacing(y=20, z=20, x=20)
        yz_grid.rotate(90, 0, 1, 0)
        yz_grid.translate(-100, 0, 100)
        yz_grid.setColor((0.7, 0.7, 0.7, 0.2))
        self.gl_view.addItem(yz_grid)

        axis = gl.GLAxisItem(size=pg.Vector(20, 20, 20))
        self.gl_view.addItem(axis)

    def toggle_debug_mode(self) -> None:
        """Toggle debug mode on/off."""
        self.debug_mode = self.debug_action.isChecked()
        if not self.debug_mode:
            self.image_label.clear()

    def load_stl_file(self) -> None:
        """Load and display an STL file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open STL File", "", "STL Files (*.stl)"
        )
        if not file_path:
            return

        self.current_stl_file = file_path
        self.current_scad_file = os.path.splitext(file_path)[0] + ".scad"
        self.verify_scad_file = None
        self.convert_action.setEnabled(True)
        self.set_output_action.setEnabled(True)
        self.verify_action.setEnabled(True)
        self.use_existing_scad_action.setEnabled(True)
        self.use_existing_scad_action.setChecked(False)
        self.select_verify_scad_action.setEnabled(True)
        self.image_label.clear()

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
            self.status_label.setText(
                f"Loaded: {os.path.basename(file_path)} | Size {size:.2f} | "
                f"Vertices {len(vertices)} | Faces {len(faces)}"
            )
        except Exception as exc:
            msg = f"Error loading STL file: {exc}"
            self.status_label.setText(msg)
            QtWidgets.QMessageBox.critical(self, "Loading Error", msg)
            return

        self.center_object()
        self.fit_to_window()
        self.update_info_label()

    def convert_to_scad(self) -> None:
        """Convert the loaded STL file to OpenSCAD format."""
        if not self.current_stl_file:
            return

        output_file = self.current_scad_file or (os.path.splitext(self.current_stl_file)[0] + ".scad")
        self.current_scad_file = output_file

        self.worker = ConversionWorker(
            self.current_stl_file,
            output_file,
            tolerance=float(self.convert_tol_spin.value()),
            debug=self.debug_mode,
            parametric=self.parametric_action.isChecked(),
        )
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.error.connect(self.conversion_error)

        self.convert_action.setEnabled(False)
        self.verify_action.setEnabled(False)
        self.worker.start()

    def verify_current_model(self) -> None:
        """Verify currently loaded model with configured tolerance/report options."""
        if not self.current_stl_file:
            return

        if not self.current_scad_file:
            self.current_scad_file = os.path.splitext(self.current_stl_file)[0] + ".scad"

        use_existing_scad = self.use_existing_scad_action.isChecked()
        scad_file = self.current_scad_file
        if use_existing_scad:
            scad_file = self.verify_scad_file or self.current_scad_file
            if not scad_file or not os.path.exists(scad_file):
                file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self,
                    "Select SCAD File for Verification",
                    os.path.dirname(self.current_stl_file),
                    "SCAD Files (*.scad)",
                )
                if not file_path:
                    self.status_label.setText("Verification canceled: no SCAD file selected.")
                    return
                self.verify_scad_file = file_path
                scad_file = file_path

        tolerance = {
            "volume": float(self.volume_tol_spin.value()),
            "surface_area": float(self.area_tol_spin.value()),
            "bounding_box": float(self.bbox_tol_spin.value()),
        }
        visualize = self.visualize_action.isChecked() or self.html_report_action.isChecked()

        self.worker = VerificationWorker(
            self.current_stl_file,
            scad_file,
            tolerance=tolerance,
            conversion_tolerance=float(self.convert_tol_spin.value()),
            parametric=self.parametric_action.isChecked(),
            regenerate_scad=not use_existing_scad,
            visualize=visualize,
            html_report=self.html_report_action.isChecked(),
        )
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.verification_finished)
        self.worker.error.connect(self.verification_error)

        self.convert_action.setEnabled(False)
        self.verify_action.setEnabled(False)
        self.worker.start()

    def select_output_scad_file(self) -> None:
        """Select output SCAD path for conversion."""
        if not self.current_stl_file:
            return
        initial = self.current_scad_file or (os.path.splitext(self.current_stl_file)[0] + ".scad")
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select Output SCAD File",
            initial,
            "SCAD Files (*.scad)",
        )
        if not file_path:
            return

        self.current_scad_file = file_path
        self.status_label.setText(f"Output SCAD set: {file_path}")

    def select_verify_scad_file(self) -> None:
        """Select an existing SCAD file for verification mode."""
        if not self.current_stl_file:
            return
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select SCAD File for Verification",
            os.path.dirname(self.current_stl_file),
            "SCAD Files (*.scad)",
        )
        if not file_path:
            return

        self.verify_scad_file = file_path
        self.status_label.setText(f"Verify SCAD set: {file_path}")

    def toggle_use_existing_scad(self) -> None:
        """Toggle whether verification should use an existing SCAD file."""
        enabled = self.use_existing_scad_action.isChecked()
        mode = "existing SCAD" if enabled else "regenerate SCAD from STL"
        self.status_label.setText(f"Verification mode: {mode}")

    def update_status(self, message: str) -> None:
        """Update the status label with a message."""
        self.status_label.setText(message)

    def conversion_finished(self, stats: ConversionStats) -> None:
        """Handle successful conversion completion."""
        self.convert_action.setEnabled(True)
        self.verify_action.setEnabled(True)

        reduction = 100 * (1 - stats.deduplicated_vertices / stats.original_vertices)
        self.status_label.setText(
            f"Conversion successful | Vertices {stats.deduplicated_vertices} "
            f"({reduction:.1f}% reduction) | Faces {stats.faces} | SCAD {self.current_scad_file}"
        )

        if self.debug_mode and self.current_scad_file:
            scad_base = os.path.splitext(self.current_scad_file)[0]
            png_file = f"{scad_base}_preview.png"
            if os.path.exists(png_file):
                pixmap = QPixmap(png_file)
                self.image_label.setPixmap(
                    pixmap.scaled(
                        self.image_label.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )

    def conversion_error(self, error_message: str) -> None:
        """Handle conversion error."""
        self.convert_action.setEnabled(True)
        self.verify_action.setEnabled(True)
        self.status_label.setText(f"Conversion failed: {error_message}")
        QtWidgets.QMessageBox.critical(self, "Conversion Error", error_message)

    def verification_finished(self, payload: Dict[str, Any]) -> None:
        """Handle successful verification completion."""
        self.convert_action.setEnabled(True)
        self.verify_action.setEnabled(True)

        result = payload["result"]
        report_file = payload["report_file"]
        html_file = payload.get("html_file")
        scad_file = payload.get("scad_file")
        status = "PASSED" if result.passed else "FAILED"

        details = [f"Verification {status}", f"JSON: {report_file}"]
        if scad_file:
            details.append(f"SCAD: {scad_file}")
        if html_file:
            details.append(f"HTML: {html_file}")
        self.status_label.setText(" | ".join(details))

        QtWidgets.QMessageBox.information(
            self,
            "Verification Complete",
            "\n".join(details),
        )

    def verification_error(self, error_message: str) -> None:
        """Handle verification error."""
        self.convert_action.setEnabled(True)
        self.verify_action.setEnabled(True)
        self.status_label.setText(f"Verification failed: {error_message}")
        QtWidgets.QMessageBox.critical(self, "Verification Error", error_message)

    def center_object(self) -> None:
        """Center the 3D object in the view."""
        if self.mesh_data is None:
            return

        vertices = self.mesh_data.vertexes()
        center = vertices.mean(axis=0)
        size = float(np.max(vertices.max(axis=0) - vertices.min(axis=0)))
        distance = max(size * 2, 1.0)

        self.gl_view.opts["center"] = pg.Vector(center[0], center[1], center[2])
        self.gl_view.setCameraPosition(distance=distance, elevation=45, azimuth=45)
        self.gl_view.update()
        self.update_info_label()

    def rotate_object(self, axis: str) -> None:
        """Rotate the view to look along the specified axis."""
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
        self.update_info_label()

    def fit_to_window(self) -> None:
        """Scale the view to fit the object."""
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
        self.update_info_label()

    def select_color(self) -> None:
        """Open a color picker and update the object color."""
        if self.mesh_data is None:
            return

        initial_color = QColor(180, 180, 180)
        color = QtWidgets.QColorDialog.getColor(initial=initial_color)
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
        self.update_info_label()

    def update_info_label(self) -> None:
        """Update the information label with current view settings."""
        pos = self.gl_view.cameraPosition()
        color_str = (
            f"({self.current_color[0]:.2f}, "
            f"{self.current_color[1]:.2f}, "
            f"{self.current_color[2]:.2f})"
        )
        self.info_label.setText(
            f"Camera X:{pos.x():.1f} Y:{pos.y():.1f} Z:{pos.z():.1f} | Color {color_str}"
        )
