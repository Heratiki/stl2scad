"""
Core conversion functionality for transforming STL files to OpenSCAD format.
"""

import numpy as np
import stl
import logging
import subprocess
import os
import sys
import re
from typing import Tuple, List, Dict
from dataclasses import dataclass

def get_openscad_path():
    """Get OpenSCAD executable path and verify version requirements."""
    REQUIRED_VERSION = "2025.02.19"
    
    def check_version(path):
        """Check if OpenSCAD at path is nightly build with required version."""
        try:
            print(f"Checking OpenSCAD version at: {path}")
            if sys.platform == "win32":
                # Use PowerShell to run OpenSCAD command
                cmd = ['powershell', '-Command', f"& '{path}' --info"]
            else:
                cmd = [path, '--info']
                
            print("Running command:", cmd)
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.stderr:
                print("stderr output:", result.stderr)
            if result.stdout:
                print("stdout output:", result.stdout)
                
            info = result.stdout.strip() if result.stdout else ""
            print(f"Found OpenSCAD info: {info}")
            
            # Check if it's a nightly build
            if 'nightly' not in info.lower() and 'dev' not in info.lower():
                return False, "Not a nightly/dev build"
            
            # Extract version number (assuming format contains "2025.02.19" somewhere)
            version_match = re.search(r'(\d{4}\.\d{2}\.\d{2})', info)
            if not version_match:
                return False, "Could not determine version"
            
            version = version_match.group(1)
            print(f"Detected version: {version}")
            if version < REQUIRED_VERSION:
                return False, f"Version {version} is older than required {REQUIRED_VERSION}"
                
            print(f"Version check passed: {version} >= {REQUIRED_VERSION}")
            return True, info
        except subprocess.CalledProcessError as e:
            print(f"Command failed with return code {e.returncode}")
            if e.stdout:
                print("stdout:", e.stdout)
            if e.stderr:
                print("stderr:", e.stderr)
            return False, f"Error checking version: {e}"
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return False, f"Error checking version: {str(e)}"
    
    if sys.platform == "win32":
        base_path = r"C:\Program Files\OpenSCAD (Nightly)"
        exe_path = os.path.join(base_path, "openscad.exe")  # For GUI operations
        com_path = os.path.join(base_path, "openscad.com")  # For command-line operations
        
        if not (os.path.exists(exe_path) and os.path.exists(com_path)):
            raise FileNotFoundError(
                "OpenSCAD (Nightly) not found. Please install OpenSCAD (Nightly) version 25.02.19 or later "
                "from https://openscad.org/downloads.html#snapshots. The regular OpenSCAD release does not "
                "support the required debug features."
            )
        
        # Verify version
        is_valid, message = check_version(com_path)
        if not is_valid:
            raise FileNotFoundError(
                f"Invalid OpenSCAD version: {message}. Please install OpenSCAD (Nightly) version 25.02.19 or later "
                "from https://openscad.org/downloads.html#snapshots"
            )
        
        return com_path  # Return the .com path for command-line operations
    else:
        # For non-Windows systems
        paths = ["/usr/bin/openscad", "/usr/local/bin/openscad"]
        for path in paths:
            if os.path.exists(path):
                is_valid, message = check_version(path)
                if is_valid:
                    return path
                print(f"Warning: Found OpenSCAD at {path} but {message}", file=sys.stderr)
                
        raise FileNotFoundError(
            "OpenSCAD (Nightly) not found. Please install OpenSCAD (Nightly) version 25.02.19 or later "
            "from https://openscad.org/downloads.html#snapshots"
        )

# Configure logging to stdout with more verbose format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s: %(message)s',
    stream=sys.stdout,
    force=True  # Override any existing handlers
)

@dataclass
class ConversionStats:
    """Statistics about the conversion process."""
    original_vertices: int
    deduplicated_vertices: int
    faces: int
    metadata: Dict[str, str]

class STLValidationError(Exception):
    """Raised when STL file validation fails."""
    pass

def validate_stl(mesh: stl.mesh.Mesh) -> None:
    """
    Validate STL mesh integrity.
    
    Args:
        mesh: The STL mesh to validate
        
    Raises:
        STLValidationError: If validation fails
    """
    if len(mesh.points) == 0:
        raise STLValidationError("Empty STL file")
    
    # Check for non-manifold edges
    edges = {}
    for i, face in enumerate(mesh.vectors):
        for j in range(3):
            edge = tuple(sorted([
                tuple(face[j]), 
                tuple(face[(j + 1) % 3])
            ]))
            if edge in edges:
                edges[edge].append(i)
            else:
                edges[edge] = [i]
    
    non_manifold = [e for e, faces in edges.items() if len(faces) > 2]
    if non_manifold:
        raise STLValidationError(f"Non-manifold edges found: {len(non_manifold)} edges")

def find_unique_vertices(points: np.ndarray, tolerance: float = 1e-6) -> Tuple[np.ndarray, Dict[int, int]]:
    """
    Deduplicate vertices within given tolerance.
    
    Args:
        points: Array of vertex coordinates
        tolerance: Distance tolerance for considering vertices identical
        
    Returns:
        Tuple of unique vertices array and mapping from original to unique indices
    """
    unique_vertices = []
    vertex_map = {}
    
    for i, vertex in enumerate(points):
        found = False
        for j, unique in enumerate(unique_vertices):
            if np.allclose(vertex, unique, rtol=tolerance):
                vertex_map[i] = j
                found = True
                break
        if not found:
            vertex_map[i] = len(unique_vertices)
            unique_vertices.append(vertex)
    
    return np.array(unique_vertices), vertex_map

def optimize_scad(points: np.ndarray, faces: List[List[int]]) -> Tuple[np.ndarray, List[List[int]]]:
    """
    Optimize SCAD output for better performance.
    
    Args:
        points: Array of vertex coordinates
        faces: List of face vertex indices
        
    Returns:
        Tuple of optimized points array and faces list
    """
    # Remove unused vertices
    used_vertices = set()
    for face in faces:
        used_vertices.update(face)
    
    vertex_map = {}
    new_points = []
    for i, vertex in enumerate(points):
        if i in used_vertices:
            vertex_map[i] = len(new_points)
            new_points.append(vertex)
    
    # Remap faces to new vertex indices
    new_faces = [[vertex_map[v] for v in face] for face in faces]
    
    return np.array(new_points), new_faces

def extract_metadata(mesh: stl.mesh.Mesh) -> Dict[str, str]:
    """
    Extract metadata from STL file.
    
    Args:
        mesh: The STL mesh to extract metadata from
        
    Returns:
        Dictionary of metadata
    """
    metadata = {}
    if hasattr(mesh, 'name') and mesh.name:
        metadata['name'] = mesh.name.decode('utf-8').strip()
    metadata['volume'] = str(mesh.get_mass_properties()[0])
    metadata['bbox'] = str(tuple(zip(mesh.min_, mesh.max_)))
    return metadata

def render_stl_preview(stl_mesh: stl.mesh.Mesh, output_path: str) -> None:
    """
    Render STL preview using VTK.
    
    Args:
        stl_mesh: The STL mesh to render
        output_path: Path to save the preview image
    """
    try:
        print("Attempting to render STL preview...")
        import vtk
        from vtk.util import numpy_support
        print("VTK imported successfully")
        
        # Create points array
        print("Creating points array...")
        points = vtk.vtkPoints()
        vertices = stl_mesh.vectors.reshape(-1, 3)
        for vertex in vertices:
            points.InsertNextPoint(vertex)
            
        # Create triangles array
        print("Creating triangles array...")
        triangles = vtk.vtkCellArray()
        for i in range(0, len(vertices), 3):
            triangle = vtk.vtkTriangle()
            triangle.GetPointIds().SetId(0, i)
            triangle.GetPointIds().SetId(1, i + 1)
            triangle.GetPointIds().SetId(2, i + 2)
            triangles.InsertNextCell(triangle)
            
        # Create polydata
        print("Creating polydata...")
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(triangles)
        
        # Create mapper and actor
        print("Setting up visualization pipeline...")
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.8, 0.8, 0.8)  # Light gray
        actor.GetProperty().SetAmbient(0.1)
        actor.GetProperty().SetDiffuse(0.7)
        actor.GetProperty().SetSpecular(0.2)
        
        # Create renderer
        renderer = vtk.vtkRenderer()
        renderer.AddActor(actor)
        renderer.SetBackground(1, 1, 1)  # White background
        
        # Set up camera
        camera = renderer.GetActiveCamera()
        camera.SetPosition(1, 1, 1)  # Isometric view
        camera.SetFocalPoint(0, 0, 0)
        camera.SetViewUp(0, 0, 1)
        
        # Create render window
        render_window = vtk.vtkRenderWindow()
        render_window.SetOffScreenRendering(1)
        render_window.AddRenderer(renderer)
        render_window.SetSize(800, 600)
        
        # Render and save
        print(f"Saving preview to {output_path}...")
        render_window.Render()
        
        # Reset camera to fit scene
        renderer.ResetCamera()
        render_window.Render()
        
        # Save to PNG
        writer = vtk.vtkPNGWriter()
        window_to_image = vtk.vtkWindowToImageFilter()
        window_to_image.SetInput(render_window)
        window_to_image.Update()
        
        writer.SetFileName(output_path)
        writer.SetInputConnection(window_to_image.GetOutputPort())
        writer.Write()
        
        print("STL preview generated successfully")
        
    except ImportError as e:
        print(f"Warning: VTK import error: {str(e)}", file=sys.stderr)
        print("Install with: pip install vtk", file=sys.stderr)
    except Exception as e:
        print(f"Error generating STL preview: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()

def stl2scad(input_file: str, output_file: str, tolerance: float = 1e-6, debug: bool = False) -> ConversionStats:
    """
    Convert STL to SCAD with improved handling and optimization.

    Args:
        input_file: Path to input STL file
        output_file: Path to output SCAD file
        tolerance: Vertex deduplication tolerance
        debug: Enable debug mode (renders comparison previews)

    Returns:
        ConversionStats object with conversion statistics

    Raises:
        STLValidationError: If STL validation fails
    """
    logging.debug('Input file: %s', input_file)
    logging.debug('Output file: %s', output_file)
    logging.debug('Debug mode: %s', debug)

    try:
        stl_mesh = stl.mesh.Mesh.from_file(input_file)
        validate_stl(stl_mesh)
    except Exception as e:
        logging.error('Failed to load or validate STL: %s', str(e))
        raise

    # Extract metadata before processing
    metadata = extract_metadata(stl_mesh)
    original_vertex_count = len(stl_mesh.points.reshape(-1, 3))

    # Deduplicate vertices
    points = stl_mesh.points.reshape(-1, 3)
    unique_points, vertex_map = find_unique_vertices(points, tolerance)
    
    # Create faces using mapped vertices
    faces = []
    for i in range(0, len(points), 3):
        face = [vertex_map[i], vertex_map[i+1], vertex_map[i+2]]
        faces.append(face)

    # Optimize SCAD output
    final_points, final_faces = optimize_scad(unique_points, faces)

    # Write SCAD file with metadata as comments
    with open(output_file, "w") as f:
        # Write metadata as comments
        f.write("// STL to SCAD Conversion\n")
        for key, value in metadata.items():
            f.write(f"// {key}: {value}\n")
        f.write("\n")

        # Write the polyhedron
        f.write("polyhedron(\n")
        f.write("  points=[\n")
        for vertex in final_points:
            f.write(f"    [{vertex[0]:.6f}, {vertex[1]:.6f}, {vertex[2]:.6f}],\n")
        f.write("  ],\n")

        f.write("  faces=[\n")
        for face in final_faces:
            f.write(f"    [{face[0]}, {face[1]}, {face[2]}],\n")
        f.write("  ],\n")
        f.write("  convexity=10\n")  # Improved rendering
        f.write(");\n")

    stats = ConversionStats(
        original_vertices=original_vertex_count,
        deduplicated_vertices=len(final_points),
        faces=len(final_faces),
        metadata=metadata
    )

    if debug:
        try:
            print("\nRunning debug analysis...")
            openscad_path = get_openscad_path()
            if not openscad_path:
                raise FileNotFoundError("OpenSCAD not found in standard locations")

            # Setup debug file paths and clean up old files
            debug_dir = os.path.dirname(output_file)
            debug_base = os.path.splitext(os.path.basename(output_file))[0]
            debug_files = {
                'scad': os.path.join(debug_dir, f"{debug_base}_debug.scad"),
                'json': os.path.join(debug_dir, f"{debug_base}_analysis.json"),
                'echo': os.path.join(debug_dir, f"{debug_base}_debug.echo"),
                'png': os.path.join(debug_dir, f"{debug_base}_preview.png")
            }

            # Clean up any existing debug files
            print("\nCleaning up old debug files...")
            for name, path in debug_files.items():
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        print(f"Removed old {name} file")
                    except Exception as e:
                        print(f"Warning: Could not remove old {name} file: {e}", file=sys.stderr)

            # Assign paths for easier reference
            debug_scad = debug_files['scad']
            debug_json = debug_files['json']
            debug_echo = debug_files['echo']
            debug_png = debug_files['png']

            # Generate debug SCAD file
            with open(debug_scad, 'w') as f:
                f.write("// Original STL Import\n")
                f.write(f'import("{input_file}");\n\n')
                f.write("// Our SCAD Conversion\n")
                f.write("%{\n")  # Echo will appear in console
                f.write('  echo("=== Conversion Debug Info ===");\n')
                f.write(f'  echo("Original vertices:", {original_vertex_count});\n')
                f.write(f'  echo("Optimized vertices:", {len(final_points)});\n')
                f.write(f'  echo("Faces:", {len(final_faces)});\n')
                f.write(f'  echo("Reduction:", {100 * (1 - len(final_points)/original_vertex_count):.1f}, "%");\n')
                f.write("}\n\n")
                f.write("translate([50, 0, 0]) {\n")  # Offset for side-by-side view
                with open(output_file) as orig:
                    f.write(orig.read())
                f.write("}\n")

            # Run OpenSCAD with advanced debug options
            print("\nGenerating debug analysis...")
            print(f"Using OpenSCAD at: {openscad_path}")
            
            # Build OpenSCAD arguments
            scad_args = [
                "--backend=Manifold",  # Use faster renderer
                "--summary=all",  # Enable all statistics
                f"--summary-file='{debug_json}'",  # Save analysis to JSON
                "--view=axes,edges,scales",  # Show helpful guides
                "--autocenter",
                "--viewall",
                "--colorscheme=Tomorrow Night",
                f"-o '{debug_echo}'",  # Capture echo output
                f"-o '{debug_png}'",  # Generate preview image
                f"'{debug_scad}'"  # Input file
            ]
            
            # Use PowerShell to run OpenSCAD
            if sys.platform == "win32":
                cmd = ['powershell', '-Command', f"& '{openscad_path}' {' '.join(scad_args)}"]
            else:
                cmd = [openscad_path] + [arg.strip("'") for arg in scad_args]
                
            print("Running command:", ' '.join(cmd))
            
            try:
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                print("\nCommand output:")
                if result.stdout:
                    print("stdout:", result.stdout)
                if result.stderr:
                    print("stderr:", result.stderr)
            except subprocess.CalledProcessError as e:
                print(f"Command failed with exit code {e.returncode}")
                if e.stdout:
                    print("stdout:", e.stdout)
                if e.stderr:
                    print("stderr:", e.stderr)
                raise
            
            print("\nDebug files generated:")
            print(f"1. Comparison SCAD: {debug_scad}")
            print(f"2. Analysis JSON: {debug_json}")
            print(f"3. Debug output: {debug_echo}")
            print(f"4. Preview image: {debug_png}")
            
            # Print any OpenSCAD output
            if result.stdout:
                print("\nOpenSCAD output:")
                print(result.stdout)
            
            print("\nTo verify the conversion:")
            print(f"1. Open {debug_scad} in OpenSCAD")
            print("2. Use F5 to preview both models side by side")
            print(f"3. Check {debug_echo} for measurements")
            print(f"4. Review {debug_json} for detailed geometry analysis")

        except subprocess.CalledProcessError as e:
            print(f"Error running OpenSCAD debug: {e.stderr}", file=sys.stderr)
        except FileNotFoundError as e:
            print(f"Error: {str(e)}. Ensure OpenSCAD is installed.", file=sys.stderr)
        except Exception as e:
            print(f"Error during debug analysis: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    return stats
