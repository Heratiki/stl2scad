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
        self.current_color = (0.8, 0.8, 0.8, 1.0)  # Initial light gray color
        self.setup_ui()

    def setup_ui(self):
        """Initialize the user interface."""
        # Initialize GL view with enhanced settings
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor('w')  # White background
        
        # Set initial view parameters for better default view
        self.gl_view.opts['distance'] = 100  # Start further back
        self.gl_view.opts['elevation'] = 20  # Lower angle
        self.gl_view.opts['azimuth'] = 45   # 45-degree view
        self.gl_view.opts['fov'] = 45       # Narrower field of view for less distortion
        self.gl_view.opts['center'] = pg.Vector(0, 0, 0)  # Center at origin
        
        # Add grids for better orientation
        # XY plane grid (ground plane)
        xy_grid = gl.GLGridItem()
        xy_grid.setSize(x=200, y=200, z=1)
        xy_grid.setSpacing(x=20, y=20, z=20)
        xy_grid.translate(0, 0, 0)  # Place at origin
        xy_grid.setColor((0.7, 0.7, 0.7, 0.4))  # Semi-transparent gray
        self.gl_view.addItem(xy_grid)

        # XZ plane grid (back wall)
        xz_grid = gl.GLGridItem()
        xz_grid.setSize(x=200, z=200, y=1)
        xz_grid.setSpacing(x=20, z=20, y=20)
        xz_grid.rotate(90, 1, 0, 0)  # Rotate to XZ plane
        xz_grid.translate(0, -100, 100)  # Position as back wall
        xz_grid.setColor((0.7, 0.7, 0.7, 0.2))  # More transparent
        self.gl_view.addItem(xz_grid)

        # YZ plane grid (side wall)
        yz_grid = gl.GLGridItem()
        yz_grid.setSize(y=200, z=200, x=1)
        yz_grid.setSpacing(y=20, z=20, x=20)
        yz_grid.rotate(90, 0, 1, 0)  # Rotate to YZ plane
        yz_grid.translate(-100, 0, 100)  # Position as side wall
        yz_grid.setColor((0.7, 0.7, 0.7, 0.2))  # More transparent
        self.gl_view.addItem(yz_grid)
        
        # Add coordinate axes for reference
        axis_length = 20
        axes = gl.GLAxisItem(size=pg.Vector(axis_length, axis_length, axis_length))
        self.gl_view.addItem(axes)
        
        # Setup lighting
        self.setup_lighting()
        
    def setup_lighting(self):
        """Setup lighting for better 3D visualization."""
        # Add key light (main illumination)
        key_light = gl.GLScatterPlotItem(
            pos=np.array([[50, 50, 100]]),
            color=(1, 1, 1, 0),  # Invisible point
            size=0.1
        )
        self.gl_view.addItem(key_light)
        
        # Add fill light (softer light from opposite side)
        fill_light = gl.GLScatterPlotItem(
            pos=np.array([[-50, -50, 50]]),
            color=(0.5, 0.5, 0.5, 0),  # Invisible point
            size=0.1
        )
        self.gl_view.addItem(fill_light)
        
        # Add rim light (back light for edge definition)
        rim_light = gl.GLScatterPlotItem(
            pos=np.array([[0, -50, -50]]),
            color=(0.2, 0.2, 0.2, 0),  # Invisible point
            size=0.1
        )
        self.gl_view.addItem(rim_light)

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

        # Create layout with better proportions
        layout = QVBoxLayout()
        
        # Give the GL view more space
        self.gl_view.setMinimumSize(1000, 700)  # Larger minimum size
        layout.addWidget(self.gl_view, stretch=8)  # Much more vertical space
        
        # Add other widgets with less space
        layout.addWidget(self.image_label, stretch=1)  # Add the image label
        
        # Info and status in a horizontal layout
        info_layout = QtWidgets.QHBoxLayout()
        
        self.info_label = QtWidgets.QLabel()
        self.info_label.setAlignment(Qt.AlignLeft)
        info_layout.addWidget(self.info_label)
        
        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(Qt.AlignRight)
        info_layout.addWidget(self.status_label)
        
        layout.addLayout(info_layout, stretch=0)  # Minimal space for info

        # Set central widget
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        # Set window size and constraints
        self.resize(1200, 800)  # Larger initial size
        self.setMinimumSize(1024, 768)  # Prevent window from being too small

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
                # Create mesh with enhanced rendering settings
                self.mesh_item = gl.GLMeshItem(
                    meshdata=self.mesh_data,
                    color=self.current_color,  # Use current color
                    smooth=True,  # Enable smooth shading
                    shader='balloon',  # Better 3D appearance
                    drawFaces=True,  # Show faces
                    drawEdges=False,  # Hide edges for smoother look
                    glOptions='opaque'  # Proper depth testing
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
            # Set center point
            self.gl_view.opts['center'] = pg.Vector(center[0], center[1], center[2])
            # Set camera position for isometric view
            self.gl_view.setCameraPosition(distance=distance, elevation=45, azimuth=45)
            self.gl_view.update()

    def rotate_object(self, axis):
        """Rotate the view to look along the specified axis."""
        if self.mesh_data is not None:
            vertices = self.mesh_data.vertexes()
            center = vertices.mean(axis=0)
            size = np.max(vertices.max(axis=0) - vertices.min(axis=0))
            distance = size * 2

            # Set center point
            self.gl_view.opts['center'] = pg.Vector(center[0], center[1], center[2])
            
            # Set camera position based on axis
            if axis == 'x':
                self.gl_view.setCameraPosition(distance=distance, elevation=0, azimuth=90)
            elif axis == 'y':
                self.gl_view.setCameraPosition(distance=distance, elevation=0, azimuth=0)
            elif axis == 'z':
                self.gl_view.setCameraPosition(distance=distance, elevation=90, azimuth=0)
            
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
            
            # Set center point and adjust distance
            self.gl_view.opts['center'] = pg.Vector(center[0], center[1], center[2])
            distance = size * 2
            
            # Keep current elevation and azimuth, just update distance
            current_pos = self.gl_view.cameraPosition()
            if isinstance(current_pos, tuple):
                pos, elevation, azimuth = current_pos
            else:
                elevation = self.gl_view.opts['elevation']
                azimuth = self.gl_view.opts['azimuth']
            
            # Update camera with new distance but keep orientation
            self.gl_view.setCameraPosition(distance=distance, elevation=elevation, azimuth=azimuth)
            self.gl_view.update()

    def select_color(self):
        """Open a color picker and update the object color."""
        initial_color = QColor(180, 180, 180)  # Initial color is light gray
        color = QtWidgets.QColorDialog.getColor(initial=initial_color)

        if color.isValid():
            # Store current color
            self.current_color = color.getRgbF()
            
            # Remove old mesh item
            self.gl_view.removeItem(self.mesh_item)
            
            # Create new mesh item with updated color and enhanced rendering
            self.mesh_item = gl.GLMeshItem(
                meshdata=self.mesh_data,
                color=self.current_color,
                smooth=True,
                shader='balloon',
                drawFaces=True,
                drawEdges=False,
                glOptions='opaque'
            )
            
            # Add new mesh item
            self.gl_view.addItem(self.mesh_item)
            self.update_info_label()

    def update_info_label(self):
        """Update the information label with current view settings."""
        pos = self.gl_view.cameraPosition()
        x, y, z = pos.x(), pos.y(), pos.z()
        color_str = f"({self.current_color[0]:.2f}, {self.current_color[1]:.2f}, {self.current_color[2]:.2f})"
        self.info_label.setText(f"Camera Position - X: {x:.1f}, Y: {y:.1f}, Z: {z:.1f}, Color: {color_str}")
