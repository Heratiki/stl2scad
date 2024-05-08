import sys
import os
import numpy as np
import stl
import logging

logging.basicConfig(filename='stl2scad.log', level=logging.DEBUG)

def stl2scad(input_file, output_file):
    logging.debug('Input file: %s', input_file)
    logging.debug('Output file: %s', output_file)

    stl_mesh = stl.mesh.Mesh.from_file(input_file)
    logging.debug('Read STL file')

    input_file_name = os.path.basename(input_file)
    logging.debug('Input file name: %s', input_file_name)

    output_file_name = os.path.splitext(input_file_name)[0] + ".scad"
    logging.debug('Output file name: %s', output_file_name)

    output_file_dir = os.path.dirname(input_file)
    logging.debug('Output file directory: %s', output_file_dir)

    with open(os.path.join(output_file_dir, output_file_name), "w") as output_file:
        logging.debug('Opened output file for writing')
        output_file.write("polyhedron(\n")
        output_file.write("  points=[\n")
        for vertex in stl_mesh.points.reshape(-1, 3):
            output_file.write(f"    [{vertex[0]}, {vertex[1]}, {vertex[2]}],\n")
        output_file.write("  ],\n")

        output_file.write("  faces=[\n")
        for face in stl_mesh.points.reshape(-1, 9):
            face_indices = []
            for vertex in face.reshape(3, 3):
                index = np.where(np.all(stl_mesh.points.reshape(-1, 3) == vertex, axis=1))[0][0]
                face_indices.append(index)
            output_file.write(f"    [{face_indices[0]}, {face_indices[1]}, {face_indices[2]}],\n")
        output_file.write("  ]\n")
        output_file.write(");\n")

def usage():
    print("Usage: python3 stl2scad.py <input.stl> <output.scad>")
    print("Converts an STL file to an OpenSCAD file.")
    print("The output file will be a 3D object with the same name as the input file.")
    print("The output file will be placed in the same directory as the input file.")
    
def main():
    if len(sys.argv) != 3:
        usage()
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    stl2scad(input_file, output_file)

if __name__ == "__main__":
    main()