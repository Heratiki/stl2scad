# import numpy as np
from stl import mesh
import matplotlib.pyplot as plt
from mpl_toolkits import mplot3d    # This is required before you can load Axes3D  unless you load it directly with from mpl_toolkits.mplot3d import Axes3D
# from mpl_toolkits.mplot3d import Axes3D

def display_stl(filename):
    # Load the STL files and add the vectors to the plot
    your_mesh = mesh.Mesh.from_file(filename)
    figure = plt.figure()
    axes = mplot3d.Axes3D(figure)

    # Add the vectors to the plot
    axes.add_collection3d(mplot3d.art3d.Poly3DCollection(your_mesh.vectors, edgecolor='k'))

    # Auto scale to the mesh size
    scale = your_mesh.points.flatten()
    axes.auto_scale_xyz(scale, scale, scale)

    # Show the plot to the screen
    plt.show()