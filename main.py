import PySimpleGUI as sg
import trimesh
import pyglet

# Define the layout of the GUI
gui_layout = [
    [sg.Text("Choose an STL file:")],
    [sg.Input(key="STL_FILE_PATH"), sg.FileBrowse()],
    [sg.Button("Process STL File")],
    [sg.Graph((800, 600), (0, 0), (800, 600), key="GRAPH_DISPLAY")]
]

# Create the window
gui_window = sg.Window('STL File Processor', gui_layout)

while True:
    event, values = gui_window.read()
    if event == sg.WINDOW_CLOSED:
        break
    elif event == "Process STL File":
        stl_file_path = values["STL_FILE_PATH"]
        if stl_file_path:
            stl_mesh = trimesh.load(stl_file_path)
            if isinstance(stl_mesh, list):
                stl_mesh = stl_mesh[0]  # Get the first mesh from the list
            trimesh.viewer.SceneViewer(stl_mesh).show()  # Show the 3D viewer

# Close the window
gui_window.close()