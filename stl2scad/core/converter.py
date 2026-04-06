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
import tempfile
import json
from typing import Tuple, List, Dict, Optional, Union
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
        command = [(openscad_path or "openscad")] + args
        logging.info(f"Executing command: {' '.join(str(c) for c in command)}")

        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)

        # Always write output to log file so callers (e.g. version check) can read it
        with open(log_file, 'w', encoding='utf-8') as f:
            if result.stdout:
                f.write(result.stdout)
            if result.stderr:
                f.write(result.stderr)

        if result.stdout:
            logging.debug(f"Command output: {result.stdout}")
        if result.stderr:
            logging.warning(f"Command stderr: {result.stderr}")

        if result.returncode != 0:
            logging.error(f"Command failed with exit code {result.returncode}.")
            return False

        logging.info("Command completed successfully")
        return True

    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout} seconds. This may indicate that OpenSCAD is having trouble processing the file or the system is under heavy load.")
        return False
    except Exception as e:
        logging.error(f"Unexpected error executing OpenSCAD: {str(e)}")
        logging.debug("Stack trace:", exc_info=True)
        return False

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
            # Use a temp file so the log doesn't litter the working directory
            tmp_fd, log_file = tempfile.mkstemp(suffix='.log', prefix='openscad_version_')
            os.close(tmp_fd)

            try:
                if not run_openscad("Version check", args, log_file, path):
                    logging.error("Failed to run OpenSCAD version check")
                    return False, "Failed to run version check"

                # Read version info from log
                with open(log_file, 'r', encoding='utf-8') as f:
                    info = f.read().strip()
            finally:
                try:
                    os.unlink(log_file)
                except OSError:
                    pass
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
            # Compare versions using tuples for proper semantic versioning
            version_tuple = tuple(map(int, version.split('.')))
            required_tuple = tuple(map(int, required_version.split('.')))
            if version_tuple < required_tuple:
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

# Configure logging for subprocesses (detailed format used in stl2scad function)
# NOTE: Module-level logging config is removed to avoid interfering with pytest.
# Logging is configured in the stl2scad() function when needed.

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

def validate_stl(mesh: stl.mesh.Mesh, tolerance: float = 1e-6) -> None:
    """
    Validate STL mesh integrity.

    Args:
        mesh: The STL mesh to validate
        tolerance: Grid cell size for vertex snapping

    Raises:
        STLValidationError: If validation fails
    """
    if len(mesh.points) == 0:
        raise STLValidationError("Empty STL file")

    # Check for non-manifold edges using integer grids to avoid float fragility
    scale = 1.0 / tolerance
    quantized_vectors = np.round(mesh.vectors * scale).astype(np.int64)

    edges: Dict[Tuple[Tuple[int, int, int], Tuple[int, int, int]], List[int]] = {}
    for i, face in enumerate(quantized_vectors):
        if len(set(tuple(p) for p in face)) < 3:
            continue
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
    Deduplicate vertices within given tolerance using O(n log n) numpy sorting.

    Vertices are snapped to a grid of size `tolerance` before comparison so that
    nearly-identical coordinates (within one grid cell) are treated as the same
    point.  The first occurrence of each unique grid cell is used as the
    canonical vertex coordinate.

    Args:
        points: Array of vertex coordinates, shape (N, 3)
        tolerance: Grid cell size for vertex snapping (default 1e-6)

    Returns:
        Tuple of (unique_points array, vertex_map dict) where vertex_map[i]
        gives the index into unique_points for original vertex i.
    """
    # Round to a grid defined by tolerance to merge nearly-identical vertices.
    # Multiply by 1/tolerance then round to integer so that any two points
    # closer than `tolerance` map to the same integer cell.
    scale = 1.0 / tolerance
    rounded = np.round(points * scale).astype(np.int64)

    # np.unique on rows is O(n log n) via lexicographic sort.
    # first_occurrence[j] = index in `points` of the first row matching
    #                        the j-th unique rounded row (sorted order).
    # inverse[i]          = index into unique rows for original row i.
    _, first_occurrence, inverse = np.unique(
        rounded, axis=0, return_index=True, return_inverse=True
    )

    # Use original (unrounded) coordinates for the canonical vertices so we
    # don't shift geometry by up to half a tolerance cell.
    unique_points = points[first_occurrence]

    vertex_map: Dict[int, int] = {i: int(inverse[i]) for i in range(len(points))}

    return unique_points, vertex_map

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
        # Binary STL headers are 80 bytes padded with null bytes; strip them
        # along with whitespace so they don't end up embedded in SCAD comments
        # (a null byte in a comment causes OpenSCAD to report a parse error).
        raw_name = mesh.name.decode('utf-8', errors='replace')
        metadata['name'] = raw_name.replace('\x00', '').strip()
    with np.errstate(all='ignore'):
        volume = float(mesh.get_mass_properties()[0])
    metadata['volume'] = str(volume) if np.isfinite(volume) else "unknown"
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

    .. note::
        TODO: This function is optional/incomplete.  VTK is not listed as a
        required dependency (it is not in requirements.txt), so it will silently
        do nothing on most installs.  Either add vtk to the dependencies and
        document the requirement, or remove this function and rely solely on the
        OpenSCAD-based --render preview generated in debug mode.
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
    logging.debug('Starting STL to SCAD conversion')
    logging.debug('Input file: %s', input_file)
    logging.debug('Output file: %s', output_file)
    logging.debug('Debug mode: %s', debug)
    if tolerance <= 0:
        raise ValueError("Tolerance must be positive")

    try:
        stl_mesh = stl.mesh.Mesh.from_file(input_file)
        validate_stl(stl_mesh, tolerance)
    except Exception as e:
        logging.error('Failed to load or validate STL: %s', str(e))
        raise

    # Extract metadata before processing
    metadata = extract_metadata(stl_mesh)
    original_vertex_count = len(stl_mesh.points.reshape(-1, 3))

    # Deduplicate vertices
    points = stl_mesh.points.reshape(-1, 3)
    unique_points, vertex_map = find_unique_vertices(points, tolerance)
    
    # Create faces using mapped vertices and filter degenerate triangles that
    # collapse during vertex snapping.
    faces: List[List[int]] = []
    degenerate_faces_removed = 0
    for i in range(0, len(points), 3):
        face = [vertex_map[i], vertex_map[i+1], vertex_map[i+2]]
        if len(set(face)) < 3:
            degenerate_faces_removed += 1
            continue
        faces.append(face)

    if not faces:
        raise STLValidationError(
            "No valid faces remain after vertex deduplication. "
            "Try reducing the tolerance."
        )
    if degenerate_faces_removed:
        metadata['degenerate_faces_removed'] = str(degenerate_faces_removed)
        logging.warning(
            "Filtered %d degenerate face(s) after vertex deduplication.",
            degenerate_faces_removed
        )

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
            
            # Generate preview image using full render mode.
            # --preview=throwntogether requires an active OpenGL context and
            # fails when invoked via openscad.com; --render works headlessly.
            preview_args = [
                "--render",
                "--summary=all",
                "--summary-file", debug_json,
                "--autocenter",
                "--viewall",
                "-o", debug_png,
                debug_scad
            ]
            if not run_openscad("Preview image", preview_args, f"{debug_base}_preview.log", openscad_path):
                success = False
                logging.warning("Preview image generation failed")

            # Generate echo output
            echo_args = [
                "--backend=Manifold",
                "--render",
                "-o", debug_echo,
                debug_scad
            ]
            if not run_openscad("Debug output", echo_args, f"{debug_base}_echo.log", openscad_path):
                success = False
                logging.warning("Debug output generation failed")

            # Fallbacks for analysis JSON when the installed OpenSCAD build
            # does not support --summary-file (or does not emit it for this run).
            json_exists = os.path.exists(debug_json) and os.path.getsize(debug_json) > 0
            if not json_exists:
                legacy_analysis_args = [
                    "--render",
                    "--quiet",
                    "--export-format", "json",
                    "-o", debug_json,
                    debug_scad
                ]
                if not run_openscad(
                    "Analysis data (legacy JSON export)",
                    legacy_analysis_args,
                    f"{debug_base}_analysis.log",
                    openscad_path
                ):
                    logging.warning("Legacy JSON export not available; writing fallback analysis JSON.")

            json_exists = os.path.exists(debug_json) and os.path.getsize(debug_json) > 0
            if not json_exists:
                fallback_analysis = {
                    "note": "Fallback analysis generated by stl2scad because OpenSCAD JSON export is unavailable.",
                    "conversion": {
                        "input_file": os.path.abspath(input_file),
                        "output_file": os.path.abspath(output_file),
                        "original_vertices": original_vertex_count,
                        "optimized_vertices": len(final_points),
                        "faces": len(final_faces),
                        "degenerate_faces_removed": degenerate_faces_removed,
                    },
                    "metadata": metadata
                }
                with open(debug_json, "w", encoding="utf-8") as analysis_file:
                    json.dump(fallback_analysis, analysis_file, indent=2)

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
