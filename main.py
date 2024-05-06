import PySimpleGUI as sg
import trimesh
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

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

            # Create a new figure for the 3D plot
            fig = plt.figure()
            ax = fig.add_subplot(111, projection='3d')

            # Plot the vertices of the mesh
            ax.scatter(stl_mesh.vertices[:,0], stl_mesh.vertices[:,1], stl_mesh.vertices[:,2])

            # Show the 3D plot
            plt.show()

# Close the window
gui_window.close()