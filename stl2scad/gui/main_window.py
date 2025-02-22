"""
Main window implementation for the STL to OpenSCAD converter GUI.
"""

import os
import numpy as np
from stl import mesh
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QProgressDialog, QLabel
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
import pyqtgraph as pg
import pyqtgraph.opengl as gl

from stl2scad.core.converter import stl2scad, ConversionStats

class ConversionWorker(QThread):
    """Worker thread for STL to OpenSCAD conversion."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(ConversionStats)
    error = pyqtSignal(str)

    def __init__(self, input_file, output_file, tolerance=1e-6, debug=False):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.tolerance = tolerance
        self.debug = debug

    def run(self):
        try:
            self.progress.emit("Loading STL file...")
            stats = stl2scad(self.input_file, self.output_file, self.tolerance, self.debug)
            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QtWidgets.QMainWindow):
    """Main window for the STL to OpenSCAD converter application."""
    
    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)
        self.current_stl_file = None
        self.debug_mode = False
        self.setup_ui()

    def setup_ui(self):
        """Initialize the user interface."""
        self.gl_view = gl.GLViewWidget()  # For STL preview

        # QLabel for displaying the rendered SCAD image
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 300)  # Set a minimum size

        # Create a toolbar
        self.toolbar = self.addToolBar("Tools")
        self.toolbar.setMovable(False)

        # Create actions
        self.open_file_action = QtWidgets.QAction("Open STL File", self)
        self.open_file_action.triggered.connect(self.load_stl_file)
        self.toolbar.addAction(self.open_file_action)

        self.convert_action = QtWidgets.QAction("Convert to SCAD", self)
        self.convert_action.triggered.connect(self.convert_to_scad)
        self.convert_action.setEnabled(False)
        self.toolbar.addAction(self.convert_action)

        self.center_action = QtWidgets.QAction("Center", self)
        self.center_action.triggered.connect(self.center_object)
        self.toolbar.addAction(self.center_action)

        self.rotate_x_action = QtWidgets.QAction("Rotate to X", self)
        self.rotate_x_action.triggered.connect(lambda: self.rotate_object('x'))
        self.toolbar.addAction(self.rotate_x_action)

        self.rotate_y_action = QtWidgets.QAction("Rotate to Y", self)
        self.rotate_y_action.triggered.connect(lambda: self.rotate_object('y'))
        self.toolbar.addAction(self.rotate_y_action)

        self.rotate_z_action = QtWidgets.QAction("Rotate to Z", self)
        self.rotate_z_action.triggered.connect(lambda: self.rotate_object('z'))
        self.toolbar.addAction(self.rotate_z_action)

        self.fit_action = QtWidgets.QAction("Fit to Window", self)
        self.fit_action.triggered.connect(self.fit_to_window)
        self.toolbar.addAction(self.fit_action)

        self.color_action = QtWidgets.QAction("Select Color", self)
        self.color_action.triggered.connect(self.select_color)
        self.toolbar.addAction(self.color_action)

        # Add debug mode checkbox
        self.debug_action = QtWidgets.QAction("Debug Mode", self, checkable=True)
        self.debug_action.triggered.connect(self.toggle_debug_mode)
        self.toolbar.addAction(self.debug_action)


        # Create layout
        layout = QVBoxLayout()
        layout.addWidget(self.gl_view)
        layout.addWidget(self.image_label)  # Add the image label

        # Info label
        self.info_label = QtWidgets.QLabel()
        self.info_label.setAlignment(Qt.AlignBottom)
        layout.addWidget(self.info_label)


        # Status label for conversion
        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(Qt.AlignBottom)
        layout.addWidget(self.status_label)

        # Set central widget
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        # Resize window
        self.resize(800, 600)

    def toggle_debug_mode(self):
        """Toggle debug mode on/off."""
        self.debug_mode = self.debug_action.isChecked()
        if not self.debug_mode:
            self.image_label.clear() # Clear image when debug mode is off

    def load_stl_file(self):
        """Load and display an STL file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open STL File", "", "STL Files (*.stl)")

        if file_path:
            self.current_stl_file = file_path
            self.convert_action.setEnabled(True)
            self.status_label.setText(f"Loaded: {os.path.basename(file_path)}")
            self.image_label.clear()  # Clear any previous SCAD image

            # Clear existing mesh if any
            self.gl_view.clear()

            # Load and display new mesh
            your_mesh = mesh.Mesh.from_file(file_path)
            vertices = np.concatenate(your_mesh.vectors)
            faces = np.array([(i, i+1, i+2) for i in range(0, len(vertices), 3)])
            self.mesh_data = gl.MeshData(vertexes=vertices, faces=faces)
            self.mesh_item = gl.GLMeshItem(
                meshdata=self.mesh_data,
                color=(0.7, 0.7, 0.7, 1.0),
                smooth=False,
                drawEdges=True
            )
            self.gl_view.addItem(self.mesh_item)


            # Center and fit
            self.center_object()
            self.fit_to_window()

    def convert_to_scad(self):
        """Convert the loaded STL file to OpenSCAD format."""
        if not self.current_stl_file:
            return

        output_file = os.path.splitext(self.current_stl_file)[0] + '.scad'

        # Create and configure the conversion worker
        self.worker = ConversionWorker(self.current_stl_file, output_file, debug=self.debug_mode)
        self.worker.progress.connect(self.update_status)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.error.connect(self.conversion_error)

        # Disable convert button during conversion
        self.convert_action.setEnabled(False)

        # Start conversion
        self.worker.start()

    def update_status(self, message):
        """Update the status label with a message."""
        self.status_label.setText(message)

    def conversion_finished(self, stats):
        """Handle successful conversion completion."""
    def conversion_finished(self, stats):
        """Handle successful conversion completion."""
        self.convert_action.setEnabled(True)
        reduction = 100 * (1 - stats.deduplicated_vertices/stats.original_vertices)
        self.status_label.setText(
            f"Conversion successful! Vertices: {stats.deduplicated_vertices} "
            f"(reduced by {reduction:.1f}%), Faces: {stats.faces}"
        )

        if self.debug_mode:
            # Display the rendered image
            png_file = os.path.splitext(self.current_stl_file)[0] + '.scad.png'
            if os.path.exists(png_file):
                pixmap = QPixmap(png_file)
                self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.status_label.setText("Error: SCAD rendering failed.")
                QtWidgets.QMessageBox.critical(self, "Rendering Error", "SCAD rendering failed. See console for details.")

    def conversion_error(self, error_message):
        """Handle conversion error."""
        self.convert_action.setEnabled(True)
        self.status_label.setText(f"Error: {error_message}")
        QtWidgets.QMessageBox.critical(self, "Conversion Error", error_message)

    def center_object(self):
        """Center the 3D object in the view."""
        if self.mesh_data is not None:
            center = self.mesh_data.vertexes().mean(axis=0)
            self.gl_view.opts['center'] = pg.Vector(center[0], center[1], center[2])
            self.gl_view.update()

    def rotate_object(self, axis):
        """Rotate the view to look along the specified axis."""
        if self.mesh_data is not None:
            if axis == 'x':
                self.gl_view.opts['elevation'] = 90
                self.gl_view.opts['azimuth'] = 0
            elif axis == 'y':
                self.gl_view.opts['elevation'] = 0
                self.gl_view.opts['azimuth'] = 90
            elif axis == 'z':
                self.gl_view.opts['elevation'] = 0
                self.gl_view.opts['azimuth'] = 0
            self.gl_view.update()
    
    def fit_to_window(self):
        """Scale the view to fit the object."""
        if self.mesh_data is not None:
            min_vals = self.mesh_data.vertexes().min(axis=0)
            max_vals = self.mesh_data.vertexes().max(axis=0)
            ranges = max_vals - min_vals
            self.gl_view.opts['distance'] = max(ranges)
            self.gl_view.update()

    def select_color(self):
        """Open a color picker and update the object color."""
        initial_color = QColor(180, 180, 180)  # Initial color is light gray
        color = QtWidgets.QColorDialog.getColor(initial=initial_color)

        if color.isValid():
            self.mesh_item.setColor(color.getRgbF())
            self.update_info_label()

    def update_info_label(self):
        """Update the information label with current view settings."""
        color = self.mesh_item.color()
        pos = self.gl_view.cameraPosition()
        x, y, z = pos.x(), pos.y(), pos.z()
        self.info_label.setText(f"Camera Position - X: {x}, Y: {y}, Z: {z}, Color: {color}")
