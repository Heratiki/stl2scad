
import trimesh

def display_stl(filename=None, your_mesh=None):
    if your_mesh is None:
        if filename is None:
            raise ValueError("Either a filename or a mesh must be provided.")
        your_mesh = trimesh.load_mesh(filename)

    # If a trimesh object is provided, use its show method
    your_mesh.viewer = "gl"
    your_mesh.show()
