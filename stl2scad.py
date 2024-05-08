# This script converts an STL file to an OpenSCAD file.
# Note: This is a work in progress and is not yet functional.

import sys  # For command line arguments
import os  # For file path manipulation
import numpy as np  # For matrix math
import stl  # For reading STL files
import logging  # For logging

# The following imports are commented out as they are not currently used,
# but may be useful for future enhancements:
# import re  # For regular expressions
# import math  # For math functions
# import matplotlib.pyplot as plt  # For plotting
# from mpl_toolkits.mplot3d import Axes3D  # For 3D plotting

# Set up logging
logging.basicConfig(filename='stl2scad.log', level=logging.DEBUG)

def stl2scad(input_file, output_file):
    # Log the input and output file names
    logging.debug('Input file: %s', input_file)
    logging.debug('Output file: %s', output_file)

    # Read the STL file
    stl_mesh = stl.mesh.Mesh.from_file(input_file)
    logging.debug('Read STL file')

    # Get the name of the STL file
    input_file_name = os.path.basename(input_file)
    logging.debug('Input file name: %s', input_file_name)

    # Get the name of the OpenSCAD file
    output_file_name = os.path.splitext(input_file_name)[0] + ".scad"
    logging.debug('Output file name: %s', output_file_name)

    # Get the directory of the OpenSCAD file
    output_file_dir = os.path.dirname(input_file)
    logging.debug('Output file directory: %s', output_file_dir)

    # Open the output file for writing
    with open(os.path.join(output_file_dir, output_file_name), "w") as output_file:
        logging.debug('Opened output file for writing')
        # TODO: Write vertices to the OpenSCAD file

# Function to print usage information
def usage():
    print("Usage: python3 stl2scad.py <input.stl> <output.scad>")
    print("Converts an STL file to an OpenSCAD file.")
    print("The output file will be a 3D object with the same name as the input file.")
    print("The output file will be placed in the same directory as the input file.")
    
# function to convert an STL file to an OpenSCAD file
def stl2scad(input_file, output_file):
    # read the STL file
    stl_mesh = stl.mesh.Mesh.from_file(input_file)

    # get the name of the STL file
    input_file_name = os.path.basename(input_file)

    # get the name of the OpenSCAD file
    output_file_name = os.path.splitext(input_file_name)[0] + ".scad"

    # get the directory of the OpenSCAD file
    output_file_dir = os.path.dirname(input_file)

    # Initialize the OpenSCAD file with a union operation and write the vertices and faces.
    # This creates the 3D object using OpenSCAD's polyhedron function. Eventually I'd like to
    # use OpenSCAD's other functions to create the object so that it's easier for the user
    # to alter the object after it's created. I'd also like to eventually handle color and
    # and possibly ASCII STL files.
    # https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/Primitive_Solids#polyhedron
    
    with open(os.path.join(output_file_dir, output_file_name), "w") as output_file:
        # Write vertices to the OpenSCAD file
        output_file.write("polyhedron(\n")
        output_file.write("  points=[\n")
        for vertex in stl_mesh.points.reshape(-1, 3):
            output_file.write(f"    [{vertex[0]}, {vertex[1]}, {vertex[2]}],\n")
        output_file.write("  ],\n")

        # Write faces to the OpenSCAD file
        output_file.write("  faces=[\n")
        for face in stl_mesh.points.reshape(-1, 9):
            face_indices = []
            for vertex in face.reshape(3, 3):
                index = np.where(np.all(stl_mesh.points.reshape(-1, 3) == vertex, axis=1))[0][0]
                face_indices.append(index)
            output_file.write(f"    [{face_indices[0]}, {face_indices[1]}, {face_indices[2]}],\n")
        output_file.write("  ]\n")
        output_file.write(");\n")
    output_file.close()

    # Original Implementation Initialize the OpenSCAD file with a union operation
    # This caused issues with the OpenSCAD output file not displaying the geometry correctly.
    # Instead of getting a 3D object I ended up with a point cloud of vertices.
    # I left this in just so that I can remember where I began. Slowly learning 
    # Python and OpenSCAD as I go.
    
    # output_file = open(os.path.join(output_file_dir, output_file_name), "w")
    # output_file.write("union() {\n")

    # loop through each triangle in the STL file
    # for triangle in stl_mesh.vectors:
        # loop through each vertex in the triangle
        # for vertex in triangle:
            # write the vertex to the OpenSCAD file
            # output_file.write("    translate([" + str(vertex[0]) + ", " + str(vertex[1]) + ", " + str(vertex[2]) + "])\n")
            # output_file.write("    sphere(r=0.1);\n")

    # close the OpenSCAD file
    # output_file.write("}\n")
    
    
# main function
def main():
    # check the number of command line arguments
    if len(sys.argv) != 3:
        usage()
        sys.exit(1)
    
    # get the input file
    input_file = sys.argv[1]
    
    # get the output file
    output_file = sys.argv[2]
    
    # convert the STL file to an OpenSCAD file
    stl2scad(input_file, output_file)

# call the main function
if __name__ == "__main__":
    main()  # execute only if run as a script
