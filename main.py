import PySimpleGUI as sg
from stl import mesh
from mpl_toolkits import mplot3d
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Define the layout of the GUI
gui_layout = [
    [sg.Text("Choose an STL file:")],
    [sg.Input(key="STL_FILE_PATH"), sg.FileBrowse()],
    [sg.Button("Process STL File")],
    [sg.Canvas(key='CANVAS')],
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
            poly_collection = mplot3d.art3d.Poly3DCollection(your_mesh.vectors)
            poly_collection.set_color((0.7,0.7,0.7))  # play with color
            axes.add_collection3d(poly_collection)

            # Add the plot to the PySimpleGUI window
            canvas = FigureCanvasTkAgg(figure, master=gui_window['CANVAS'].TKCanvas)
            canvas.draw()

# Close the window
gui_window.close()