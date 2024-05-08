import PySimpleGUI as sg
import trimesh

# Define the layout of the GUI
gui_layout = [
    [sg.Text("Choose an STL file:")],
    [sg.Input(key="STL_FILE_PATH"), sg.FileBrowse()],
    [sg.Button("Process STL File")]
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

            # Set the viewer to 'gl' and display the STL file using trimesh
            stl_mesh.viewer = 'gl'
            stl_mesh.show()

# Close the window
gui_window.close()