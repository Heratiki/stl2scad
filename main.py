import PySimpleGUI as sg
import numpy as np
from stl import mesh
from mpl_toolkits import mplot3d
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Define the layout of the GUI
gui_layout = [
    [sg.Text("Choose an STL file:")],
    [sg.Input(key="STL_FILE_PATH"), sg.FileBrowse()],
    [sg.Button("Process STL File")],
    [sg.Canvas(key='CANVAS', size=(500, 500))],  # Specify a size for the canvas
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
            # Load the STL files and add the vectors to the plot
            your_mesh = mesh.Mesh.from_file(stl_file_path)
            figure = plt.figure()
            axes = figure.add_subplot(projection='3d')
            axes.set_box_aspect([np.ptp(a) for a in (your_mesh.x.flatten(), your_mesh.y.flatten(), your_mesh.z.flatten())])
            poly_collection = mplot3d.art3d.Poly3DCollection(your_mesh.vectors)
            poly_collection.set_color((0.7,0.7,0.7))  # play with color
            axes.add_collection3d(poly_collection)

            # Auto scale the axes to fit the data
            axes.auto_scale_xyz(your_mesh.x.flatten(), your_mesh.y.flatten(), your_mesh.z.flatten())

            # Add the plot to the PySimpleGUI window
            canvas = FigureCanvasTkAgg(figure, master=gui_window['CANVAS'].TKCanvas)
            canvas.draw()
            canvas.get_tk_widget().pack(side='top', fill='both', expand=True)  # Pack the canvas into the GUI

# Close the window
gui_window.close()