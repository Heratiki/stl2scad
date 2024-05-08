import numpy as np
from stl import mesh
from PyQt5 import QtWidgets
from PyQt5.QtGui import QColor
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import sys



class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        self.gl_view = gl.GLViewWidget()

        self.open_file_button = QtWidgets.QPushButton("Open STL File")
        self.open_file_button.clicked.connect(self.load_stl_file)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.addWidget(self.open_file_button)
        self.layout.addWidget(self.gl_view)

        self.main_widget = QtWidgets.QWidget()
        self.main_widget.setLayout(self.layout)

        self.setCentralWidget(self.main_widget)

        # Resize the window
        self.resize(800, 600)

        # Create a toolbar
        self.toolbar = self.addToolBar("Tools")
        self.toolbar.setMovable(False)

        # Add a center action to the toolbar
        self.center_action = QtWidgets.QAction("Center", self)
        self.center_action.triggered.connect(self.center_object)
        self.toolbar.addAction(self.center_action)

        # Add rotate actions to the toolbar
        self.rotate_x_action = QtWidgets.QAction("Rotate to X", self)
        self.rotate_x_action.triggered.connect(lambda: self.rotate_object('x'))
        self.toolbar.addAction(self.rotate_x_action)

        self.rotate_y_action = QtWidgets.QAction("Rotate to Y", self)
        self.rotate_y_action.triggered.connect(lambda: self.rotate_object('y'))
        self.toolbar.addAction(self.rotate_y_action)

        self.rotate_z_action = QtWidgets.QAction("Rotate to Z", self)
        self.rotate_z_action.triggered.connect(lambda: self.rotate_object('z'))
        self.toolbar.addAction(self.rotate_z_action)

        # Add a fit to window action to the toolbar
        self.fit_action = QtWidgets.QAction("Fit to Window", self)
        self.fit_action.triggered.connect(self.fit_to_window)
        self.toolbar.addAction(self.fit_action)

        # Add a color selector action to the toolbar
        self.color_action = QtWidgets.QAction("Select Color", self)
        self.color_action.triggered.connect(self.select_color)
        self.toolbar.addAction(self.color_action)


    def load_stl_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open STL File", "", "STL Files (*.stl)")
        if file_path:
            your_mesh = mesh.Mesh.from_file(file_path)
            vertices = np.concatenate(your_mesh.vectors)
            faces = np.array([(i, i+1, i+2) for i in range(0, len(vertices), 3)])
            self.mesh_data = gl.MeshData(vertexes=vertices, faces=faces)
            self.mesh_item = gl.GLMeshItem(meshdata=self.mesh_data, color=(0.7, 0.7, 0.7, 1.0), smooth=False, drawEdges=True)
            self.gl_view.addItem(self.mesh_item)

            # Center the 3D object
            self.center_object()
            self.fit_to_window()

    def center_object(self):
        # Center the 3D object
        if self.mesh_data is not None:
            center = self.mesh_data.vertexes().mean(axis=0)
            self.gl_view.opts['center'] = pg.Vector(center[0], center[1], center[2])
            self.gl_view.update()

    def rotate_object(self, axis):
        # Rotate the 3D object
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
        # Fit the 3D object to the window
        if self.mesh_data is not None:
            min_vals = self.mesh_data.vertexes().min(axis=0)
            max_vals = self.mesh_data.vertexes().max(axis=0)
            ranges = max_vals - min_vals
            self.gl_view.opts['distance'] = max(ranges)
            self.gl_view.update()

    def select_color(self):
        # Open the color dialog and get the selected color
        initial_color = QColor(180, 180, 180)  # Initial color is light gray
        color = QtWidgets.QColorDialog.getColor(initial=initial_color)

        # If a color was selected, update the color of the GLMeshItem
        if color.isValid():
            self.mesh_item.setColor(color.getRgbF())

app = QtWidgets.QApplication(sys.argv)

window = MainWindow()
window.show()

sys.exit(app.exec_())