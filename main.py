import numpy as np
from stl import mesh
from PyQt5 import QtWidgets
import pyqtgraph.opengl as gl
import sys

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        self.gl_view = gl.GLViewWidget()
        self.setCentralWidget(self.gl_view)

        self.open_file_action = QtWidgets.QAction("Process STL File", self)
        self.open_file_action.triggered.connect(self.load_stl_file)

        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.open_file_action)

    def load_stl_file(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open STL File", "", "STL Files (*.stl)")
        if file_path:
            your_mesh = mesh.Mesh.from_file(file_path)
            vertices = np.concatenate(your_mesh.vectors)
            faces = np.array([(i, i+1, i+2) for i in range(0, len(vertices), 3)])
            mesh_data = gl.MeshData(vertexes=vertices, faces=faces)
            mesh_item = gl.GLMeshItem(meshdata=mesh_data, color=(0.7, 0.7, 0.7, 1.0), smooth=False)
            self.gl_view.addItem(mesh_item)

app = QtWidgets.QApplication(sys.argv)

window = MainWindow()
window.show()

sys.exit(app.exec_())