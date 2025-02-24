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
        # Initialize GL view with some basic settings
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor('w')  # White background
        self.gl_view.setCameraPosition(distance=40)

        # Add a grid to help with orientation
        grid = gl.GLGridItem()
        grid.setSize(x=100, y=100, z=1)
        grid.setSpacing(x=10, y=10, z=10)
        self.gl_view.addItem(grid)

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

            try:
                print(f"Loading STL file: {file_path}")
                
                # Load and display new mesh
                your_mesh = mesh.Mesh.from_file(file_path)
                print(f"STL loaded successfully:")
                print(f"Number of triangles: {len(your_mesh.vectors)}")
                print(f"Mesh bounds: {your_mesh.min_} to {your_mesh.max_}")
                
                vertices = np.concatenate(your_mesh.vectors)
                faces = np.array([(i, i+1, i+2) for i in range(0, len(vertices), 3)])
                print(f"Processed vertices: {len(vertices)}")
                print(f"Processed faces: {len(faces)}")
                
                self.mesh_data = gl.MeshData(vertexes=vertices, faces=faces)
                print("MeshData created successfully")
                
            except Exception as e:
                error_msg = f"Error loading STL file: {str(e)}"
                print(error_msg)
                self.status_label.setText(error_msg)
                QtWidgets.QMessageBox.critical(self, "Loading Error", error_msg)
                return
            try:
                print("Creating mesh with improved rendering settings")
                # Create mesh with improved rendering settings
                self.mesh_item = gl.GLMeshItem(
                    meshdata=self.mesh_data,
                    color=(0.7, 0.7, 0.7, 1.0),
                    smooth=True,  # Enable smooth shading
                    shader='shaded',  # Use shaded shader for better 3D appearance
                    drawEdges=True,
                    edgeColor=(0.2, 0.2, 0.2, 1.0),  # Darker edges for better contrast
                    glOptions='opaque'  # Ensure proper depth testing
                )
                print("GLMeshItem created successfully")
                
                self.gl_view.addItem(self.mesh_item)
                print("Mesh added to view")
                
                # Update status with mesh information
                vertices = self.mesh_data.vertexes()
                min_vals = vertices.min(axis=0)
                max_vals = vertices.max(axis=0)
                size = np.max(max_vals - min_vals)
                self.status_label.setText(
                    f"Model loaded: Size = {size:.2f} units, "
                    f"Vertices = {len(vertices)}, "
                    f"Faces = {len(self.mesh_data.faces())}"
                )
                
            except Exception as e:
                error_msg = f"Error rendering mesh: {str(e)}"
                print(error_msg)
                self.status_label.setText(error_msg)
                QtWidgets.QMessageBox.critical(self, "Rendering Error", error_msg)
                return

            # Add lighting for better 3D visualization
            light = gl.GLScatterPlotItem(
                pos=np.array([[50, 50, 50]]),
                color=(1, 1, 1, 1),
                size=0.1
            )
            self.gl_view.addItem(light)

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
            vertices = self.mesh_data.vertexes()
            center = vertices.mean(axis=0)
            
            # Set camera position relative to object size
            min_vals = vertices.min(axis=0)
            max_vals = vertices.max(axis=0)
            size = np.max(max_vals - min_vals)
            
            # Position camera at an isometric view
            distance = size * 2
            self.gl_view.setCameraPosition(
                pos=pg.Vector(distance, distance, distance),
                distance=distance,
                center=pg.Vector(center[0], center[1], center[2])
            )
            self.gl_view.update()

    def rotate_object(self, axis):
        """Rotate the view to look along the specified axis."""
        if self.mesh_data is not None:
            vertices = self.mesh_data.vertexes()
            center = vertices.mean(axis=0)
            size = np.max(vertices.max(axis=0) - vertices.min(axis=0))
            distance = size * 2

            if axis == 'x':
                pos = pg.Vector(distance, 0, 0)
                up = pg.Vector(0, 0, 1)
            elif axis == 'y':
                pos = pg.Vector(0, distance, 0)
                up = pg.Vector(0, 0, 1)
            elif axis == 'z':
                pos = pg.Vector(0, 0, distance)
                up = pg.Vector(0, 1, 0)

            self.gl_view.setCameraPosition(
                pos=pos,
                distance=distance,
                center=pg.Vector(center[0], center[1], center[2]),
                up=up
            )
            self.gl_view.update()
    
    def fit_to_window(self):
        """Scale the view to fit the object."""
        if self.mesh_data is not None:
            vertices = self.mesh_data.vertexes()
            min_vals = vertices.min(axis=0)
            max_vals = vertices.max(axis=0)
            
            # Calculate bounding box size
            size = np.max(max_vals - min_vals)
            center = (max_vals + min_vals) / 2
            
            # Set camera distance based on object size
            distance = size * 2
            current_pos = self.gl_view.cameraPosition()
            if isinstance(current_pos, tuple):
                current_pos = current_pos[0]  # Extract position vector if tuple
            
            # Maintain camera direction but adjust distance
            direction = current_pos - pg.Vector(center[0], center[1], center[2])
            if direction.length() > 0:
                direction = direction.normalized()
                new_pos = pg.Vector(center[0], center[1], center[2]) + direction * distance
                
                self.gl_view.setCameraPosition(
                    pos=new_pos,
                    distance=distance,
                    center=pg.Vector(center[0], center[1], center[2])
                )
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
