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
from typing import Tuple, List, Dict, Optional, Union, Any
from dataclasses import dataclass
from numpy.typing import NDArray

def run_openscad(description: str, args: List[str], log_file: str, openscad_path: Optional[str] = None, timeout: int = 30) -> bool:
    """Execute OpenSCAD command with proper error handling and logging.
    
    Args:
        description: Description of the command being executed
        args: List of command arguments
        log_file: Path to the log file
        openscad_path: Optional path to OpenSCAD executable
        timeout: Command timeout in seconds
        
    Returns:
        bool: True if command executed successfully, False otherwise
    """
    logging.info(f"Executing OpenSCAD: {description}")
    logging.debug(f"Command arguments: {args}")
    logging.debug(f"Log file path: {log_file}")
    logging.debug(f"Command timeout: {timeout} seconds")
    logging.debug(f"OpenSCAD path: {openscad_path or 'default'}")
    
    try:
        # Build PowerShell command for Windows
        if sys.platform == "win32":
            # Format each argument properly for PowerShell
            formatted_args = [format_arg(arg) for arg in args]
            args_str = ' '.join(formatted_args)
            # Run OpenSCAD with timeout and output redirection
            ps_script = f"""
            $ErrorActionPreference = 'Stop'
            try {{
                $output = & {format_arg(openscad_path or 'openscad')} {args_str} 2>&1
                $output | Out-File -FilePath {format_arg(log_file)} -Encoding UTF8
                if ($LASTEXITCODE -ne 0) {{
                    throw "OpenSCAD command failed with exit code $LASTEXITCODE"
                }}
                $output
            }} catch {{
                Write-Error "OpenSCAD error: $_"
                exit 1
            }}
            """
            command = ['powershell', '-NoProfile', '-Command', ps_script]
        else:
            # Direct command for non-Windows
            command = [(openscad_path or "openscad")] + args
        
        logging.info(f"Executing command: {' '.join(command)}")
        
        # Run with timeout
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
        if result.stdout:
            logging.debug(f"Command output: {result.stdout}")
        if result.stderr:
            logging.warning(f"Command stderr: {result.stderr}")
        
        # Check if OpenSCAD is still running
        if sys.platform == "win32":
            check_process = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq openscad.exe'], capture_output=True, text=True)
            if 'openscad.exe' in check_process.stdout:
                logging.warning("OpenSCAD process still running, attempting to terminate...")
                subprocess.run(['taskkill', '/F', '/IM', 'openscad.exe'], capture_output=True)
                return False
        
        logging.info("Command completed successfully")
        return True
        
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout} seconds. This may indicate that OpenSCAD is having trouble processing the file or the system is under heavy load.")
        return False
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with exit code {e.returncode}. This typically indicates an issue with the OpenSCAD command or its arguments.")
        if e.stdout:
            logging.debug(f"Command output: {e.stdout}")
        if e.stderr:
            logging.error(f"Error details: {e.stderr}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error executing OpenSCAD: {str(e)}")
        logging.debug("Stack trace:", exc_info=True)
        return False

def format_arg(arg: Any) -> str:
    """Format argument for PowerShell.
    
    Args:
        arg: The argument to format
        
    Returns:
        str: Formatted argument string
    """
    if ' ' in str(arg):
        return f'"{arg}"'
    return str(arg)

from . import config

def get_openscad_path() -> Optional[str]:
    """Get OpenSCAD executable path and verify version requirements.
    
    Returns:
        Optional[str]: Path to OpenSCAD executable if found and valid, None otherwise
    """
    def check_version(path: str) -> Tuple[bool, str]:
        """Check if OpenSCAD at path is nightly build with required version.
        
        Args:
            path: Path to OpenSCAD executable
            
        Returns:
            Tuple[bool, str]: (is_valid, message)
        """
        try:
            logging.info(f"Checking OpenSCAD version at: {path}")
            args = ['--info']
            log_file = "version_check.log"
            
            if not run_openscad("Version check", args, log_file, path):
                logging.error("Failed to run OpenSCAD version check")
                return False, "Failed to run version check"
            
            # Read version info from log
            with open(log_file, 'r', encoding='utf-8') as f:
                info = f.read().strip()
            logging.debug(f"Raw OpenSCAD info: {info}")
            
            # Clean up the info string
            info = ' '.join(info.split())
            logging.debug(f"Cleaned version info: {info}")
            
            # Extract version number
            version_match = re.search(r'Version:\s*(\d{4}\.\d{2}\.\d{2})', info)
            logging.debug(f"Version match: {version_match.group(1) if version_match else 'No match'}")
            
            # Check installation path
            logging.debug(f"Checking installation path: {path}")
            if sys.platform == "win32" and "OpenSCAD (Nightly)" not in path:
                logging.error("OpenSCAD not installed in Nightly directory")
                return False, "Not installed in OpenSCAD (Nightly) directory"
            
            if not version_match:
                logging.error("Could not determine OpenSCAD version from output")
                return False, "Could not determine version"
            
            version = version_match.group(1)
            required_version = config.get_required_version()
            logging.info(f"Detected OpenSCAD version: {version}")
            if version < required_version:
                logging.error(f"OpenSCAD version {version} is older than required {required_version}")
                return False, f"Version {version} is older than required {required_version}"
                
            logging.info(f"OpenSCAD version check passed: {version} >= {required_version}")
            return True, info
        except subprocess.CalledProcessError as e:
            logging.error(f"OpenSCAD command failed with return code {e.returncode}")
            if e.stdout:
                logging.debug(f"Command output: {e.stdout}")
            if e.stderr:
                logging.error(f"Error details: {e.stderr}")
            return False, f"Error checking version: {e}"
        except Exception as e:
            logging.error(f"Unexpected error checking OpenSCAD version: {str(e)}")
            logging.debug("Stack trace:", exc_info=True)
            return False, f"Error checking version: {str(e)}"
    
    paths_config = config.get_openscad_paths()
    if sys.platform == "win32":
        base_path = paths_config["win32"]["base"]
        exe_path = os.path.join(base_path, paths_config["win32"]["exe"])  # For GUI operations
        com_path = os.path.join(base_path, paths_config["win32"]["com"])  # For command-line operations
        
        if not (os.path.exists(exe_path) and os.path.exists(com_path)):
            raise FileNotFoundError(
                "OpenSCAD (Nightly) not found. Please install OpenSCAD (Nightly) version "
                f"{config.get_required_version()} or later from "
                "https://openscad.org/downloads.html#snapshots. The regular OpenSCAD release does not "
                "support the required debug features."
            )
        
        # Verify version
        is_valid, message = check_version(com_path)
        if not is_valid:
            raise FileNotFoundError(
                f"Invalid OpenSCAD version: {message}. Please install OpenSCAD (Nightly) version "
                f"{config.get_required_version()} or later from "
                "https://openscad.org/downloads.html#snapshots"
            )
        
        return com_path  # Return the .com path for command-line operations
    else:
        # For non-Windows systems
        platform_paths = paths_config.get(sys.platform, [])
        for path in platform_paths:
            if os.path.exists(path):
                is_valid, message = check_version(path)
                if is_valid:
                    return path
                print(f"Warning: Found OpenSCAD at {path} but {message}", file=sys.stderr)
                
        raise FileNotFoundError(
            "OpenSCAD (Nightly) not found. Please install OpenSCAD (Nightly) version "
            f"{config.get_required_version()} or later from "
            "https://openscad.org/downloads.html#snapshots"
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
    edges: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], List[int]] = {}
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

def find_unique_vertices(points: NDArray[np.float64], tolerance: float = 1e-6) -> Tuple[NDArray[np.float64], Dict[int, int]]:
    """
    Deduplicate vertices within given tolerance.
    
    Args:
        points: Array of vertex coordinates
        tolerance: Distance tolerance for considering vertices identical
        
    Returns:
        Tuple[NDArray[np.float64], Dict[int, int]]: Tuple of unique vertices array and mapping from original to unique indices
    """
    unique_vertices: List[NDArray[np.float64]] = []
    vertex_map: Dict[int, int] = {}
    
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

def optimize_scad(points: NDArray[np.float64], faces: List[List[int]]) -> Tuple[NDArray[np.float64], List[List[int]]]:
    """
    Optimize SCAD output for better performance.
    
    Args:
        points: Array of vertex coordinates
        faces: List of face vertex indices
        
    Returns:
        Tuple[NDArray[np.float64], List[List[int]]]: Tuple of optimized points array and faces list
    """
    # Remove unused vertices
    used_vertices = set()
    for face in faces:
        used_vertices.update(face)
    
    vertex_map: Dict[int, int] = {}
    new_points: List[NDArray[np.float64]] = []
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
        Dict[str, str]: Dictionary of metadata
    """
    metadata: Dict[str, str] = {}
    if hasattr(mesh, 'name') and mesh.name:
        metadata['name'] = mesh.name.decode('utf-8').strip()
    metadata['volume'] = str(mesh.get_mass_properties()[0])
    # Format bbox as a clean string with proper numeric values
    bbox_min = [float(x) for x in mesh.min_]
    bbox_max = [float(x) for x in mesh.max_]
    bbox_str = f"[{bbox_min[0]:.1f}, {bbox_min[1]:.1f}, {bbox_min[2]:.1f}] to [{bbox_max[0]:.1f}, {bbox_max[1]:.1f}, {bbox_max[2]:.1f}]"
    metadata['bbox'] = bbox_str
    return metadata

def render_stl_preview(stl_mesh: stl.mesh.Mesh, output_path: str) -> None:
    """
    Render STL preview using VTK.
    
    Args:
        stl_mesh: The STL mesh to render
        output_path: Path to save the preview image
    """
    try:
        logging.info("Attempting to render STL preview...")
        import vtk
        from vtk.util import numpy_support # type: ignore
        logging.info("VTK imported successfully")
        
        # Create points array
        logging.debug("Creating points array...")
        points = vtk.vtkPoints()
        vertices = stl_mesh.vectors.reshape(-1, 3)
        for vertex in vertices:
            points.InsertNextPoint(vertex)
            
        # Create triangles array
        logging.debug("Creating triangles array...")
        triangles = vtk.vtkCellArray()
        for i in range(0, len(vertices), 3):
            triangle = vtk.vtkTriangle()
            triangle.GetPointIds().SetId(0, i)
            triangle.GetPointIds().SetId(1, i + 1)
            triangle.GetPointIds().SetId(2, i + 2)
            triangles.InsertNextCell(triangle)
            
        # Create polydata
        logging.debug("Creating polydata...")
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(triangles)
        
        # Create mapper and actor
        logging.debug("Setting up visualization pipeline...")
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
        logging.info(f"Saving preview to {output_path}...")
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
        
        logging.info("STL preview generated successfully")
        
    except ImportError as e:
        logging.warning(f"VTK import error: {str(e)}")
        logging.warning("Install with: pip install vtk")
    except Exception as e:
        logging.error(f"Error generating STL preview: {str(e)}")
        logging.debug("Stack trace:", exc_info=True)

def stl2scad(input_file: str, output_file: str, tolerance: float = 1e-6, debug: bool = False) -> ConversionStats:
    """
    Convert STL to SCAD with improved handling and optimization.

    Args:
        input_file: Path to input STL file
        output_file: Path to output SCAD file
        tolerance: Vertex deduplication tolerance
        debug: Enable debug mode (renders comparison previews)

    Returns:
        ConversionStats: Object with conversion statistics

    Raises:
        STLValidationError: If STL validation fails
        FileNotFoundError: If OpenSCAD is not found or invalid version
    """
    # Configure logging for debugging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        force=True
    )
    
    logging.debug('Starting STL to SCAD conversion')
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
    faces: List[List[int]] = []
    for i in range(0, len(points), 3):
        face = [vertex_map[i], vertex_map[i+1], vertex_map[i+2]]
        faces.append(face)

    # Optimize SCAD output
    final_points, final_faces = optimize_scad(unique_points, faces)

    # Write SCAD file with metadata as comments
    with open(output_file, "w") as f:
        # Write metadata as comments with proper formatting
        f.write("//\n")
        f.write("// STL to SCAD Conversion\n")
        for key, value in metadata.items():
            # Clean up the value string
            clean_value = str(value).strip()  # Remove leading/trailing whitespace
            clean_value = ' '.join(clean_value.split())  # Normalize internal whitespace
            f.write(f"// {key}: {clean_value}\n")
        f.write("//\n\n")

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
            logging.info("Starting debug analysis...")
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
            logging.info("Cleaning up old debug files...")
            for name, path in debug_files.items():
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logging.debug(f"Removed old {name} file")
                    except Exception as e:
                        logging.warning(f"Could not remove old {name} file: {e}")

            # Assign paths for easier reference
            debug_scad = debug_files['scad']
            debug_json = debug_files['json']
            debug_echo = debug_files['echo']
            debug_png = debug_files['png']

            # Generate debug SCAD file with proper path handling
            with open(debug_scad, 'w') as f:
                # Write file header with metadata
                f.write("/*\n")
                f.write(" * STL to SCAD Debug View\n")
                f.write(" * Generated by stl2scad debug feature\n")
                f.write(" */\n\n")

                # Import original STL with proper path handling
                stl_path = os.path.abspath(input_file).replace("\\", "/")  # Convert to absolute path with forward slashes
                f.write("// Original STL Model\n")
                f.write(f'import("{stl_path}");\n\n')

                # Add debug information as echo statements
                f.write("// Debug Information\n")
                f.write("module debug_info() {\n")
                f.write('    echo("=== Conversion Statistics ===");\n')
                f.write(f'    echo("Original vertices:", {original_vertex_count});\n')
                f.write(f'    echo("Optimized vertices:", {len(final_points)});\n')
                f.write(f'    echo("Faces:", {len(final_faces)});\n')
                f.write(f'    echo("Reduction:", {100 * (1 - len(final_points)/original_vertex_count):.1f}, "%");\n')
                f.write("}\n")
                f.write("debug_info();\n\n")

                # Add converted SCAD model with offset
                f.write("// Converted SCAD Model\n")
                f.write("translate([100, 0, 0]) {\n")  # Increased offset for better visibility
                with open(output_file) as orig:
                    f.write(orig.read().strip())  # Remove any trailing whitespace
                f.write("\n}\n")  # Ensure proper closing brace

                # Add version info
                f.write('\necho(version=version());\n')

            # Run OpenSCAD with advanced debug options
            logging.info("Generating debug analysis...")
            logging.info(f"Using OpenSCAD at: {openscad_path}")
            
            debug_base = os.path.splitext(debug_scad)[0]
            success = True
            
            # Generate preview image with minimal options
            preview_args = [
                "--preview=throwntogether",  # Use simpler preview mode
                "--autocenter",
                "--viewall",
                "-o", format_arg(debug_png),
                format_arg(debug_scad)
            ]
            if not run_openscad("Preview image", preview_args, f"{debug_base}_preview.log", openscad_path):
                success = False
                logging.warning("Preview image generation failed")

            # Generate analysis JSON with basic options
            analysis_args = [
                "--render",  # Use render mode for analysis
                "--quiet",   # Reduce unnecessary output
                "--export-format", "json",
                "-o", format_arg(debug_json),
                format_arg(debug_scad)
            ]
            if not run_openscad("Analysis data", analysis_args, f"{debug_base}_analysis.log", openscad_path):
                success = False
                logging.warning("Analysis data generation failed")

            # Generate echo output
            echo_args = [
                "--backend=Manifold",
                "--render",
                "-o", format_arg(debug_echo),
                format_arg(debug_scad)
            ]
            if not run_openscad("Debug output", echo_args, f"{debug_base}_echo.log", openscad_path):
                success = False
                logging.warning("Debug output generation failed")

            # Verify all files were created
            files_status = {
                'Preview Image': (debug_png, os.path.exists(debug_png)),
                'Analysis JSON': (debug_json, os.path.exists(debug_json)),
                'Debug Output': (debug_echo, os.path.exists(debug_echo)),
                'Comparison SCAD': (debug_scad, os.path.exists(debug_scad))
            }
            
            logging.info("\nDebug files status:")
            for name, (path, exists) in files_status.items():
                status = "[OK]" if exists else "[MISSING]"
                size = os.path.getsize(path) if exists else 0
                if exists:
                    logging.info(f"{name}: {status} ({size:,} bytes)")
                else:
                    logging.warning(f"{name}: {status} - File was not generated at {path}")
            
            logging.info("\nTo verify the conversion:")
            logging.info(f"1. Open {debug_scad} in OpenSCAD")
            logging.info("2. Use F5 to preview both models side by side")
            logging.info(f"3. Check {debug_echo} for measurements")
            logging.info(f"4. Review {debug_json} for detailed geometry analysis")

        except subprocess.CalledProcessError as e:
            logging.error(f"Error running OpenSCAD debug: {e.stderr}")
        except FileNotFoundError as e:
            logging.error(f"Error: {str(e)}. Ensure OpenSCAD is installed.")
        except Exception as e:
            logging.error(f"Error during debug analysis: {str(e)}")
            logging.debug("Stack trace:", exc_info=True)

    return stats
