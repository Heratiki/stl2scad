import PySimpleGUI as sg
import trimesh
from trimesh import Geometry

# Define the layout of the GUI
layout = [
    [sg.Text("Choose an STL file:")],
    [sg.Input(key="-FILE-"), sg.FileBrowse()],
    [sg.Button("Process")],
    [sg.Graph((800, 600), (0, 0), (800, 600), key="-GRAPH-")]
]

# Create the window
window = sg.Window("STL Viewer", layout)

# Event loop
while True:
    event, values = window.read()
    if event == sg.WINDOW_CLOSED:
        break
        if stl_file:
            # Load the STL file
            mesh = trimesh.load(stl_file)  # Remove .geometry to access the geometry attribute
            # Load the STL file
            mesh = trimesh.load(stl_file).geometry  # Access the geometry attribute

            # Create the 3D viewer
            viewer = mesh.show()

            # Get the viewer's canvas
            canvas = viewer.window.qglviewer

            # Get the graph element from the layout
            graph = window["-GRAPH-"].TKCanvas

            # Embed the viewer's canvas into the graph element
            canvas.setParent(graph)

# Close the window
window.close()