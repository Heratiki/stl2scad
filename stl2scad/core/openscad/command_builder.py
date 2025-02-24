"""
OpenSCAD command builder with platform-aware argument handling.

This module provides classes for building and validating OpenSCAD commands,
ensuring proper shell escaping and format validation across different platforms.
"""

import os
import sys
from pathlib import Path
from typing import List, Union, Dict, Set, Optional, TypedDict, Literal, Final

class ExportFormat(TypedDict):
    """Type definition for export format configuration."""
    extensions: List[str]
    description: str

class OpenSCADError(Exception):
    """Base class for OpenSCAD-related errors."""
    pass

class CommandError(OpenSCADError):
    """Raised when command construction fails."""
    pass

class ValidationError(OpenSCADError):
    """Raised when command validation fails."""
    pass

class OpenSCADCommandBuilder:
    """
    Builds OpenSCAD commands with proper shell escaping.
    
    Example:
        >>> builder = OpenSCADCommandBuilder("/usr/bin/openscad")
        >>> builder.set_input("model.scad")
        >>> builder.set_output("output.stl")
        >>> builder.add_arg("--render")
        >>> command = builder.build()
    """
    
    def __init__(self, openscad_path: Union[str, Path]) -> None:
        """
        Initialize the command builder.
        
        Args:
            openscad_path: Path to OpenSCAD executable
        """
        self.openscad_path = Path(openscad_path)
        self.args: List[str] = []
        self.output_file: Optional[str] = None
        self.input_file: Optional[str] = None
        
    def add_arg(self, arg: str, value: Optional[Union[str, Path]] = None) -> 'OpenSCADCommandBuilder':
        """
        Add a command-line argument with optional value.
        
        Args:
            arg: Argument name (e.g., "--render")
            value: Optional argument value
            
        Returns:
            self for method chaining
        """
        self.args.append(arg)
        if value is not None:
            self.args.append(self._escape_value(value))
        return self
    
    def set_input(self, input_file: Union[str, Path]) -> 'OpenSCADCommandBuilder':
        """
        Set input SCAD file path.
        
        Args:
            input_file: Path to input file
            
        Returns:
            self for method chaining
        """
        self.input_file = self._escape_value(input_file)
        return self
    
    def set_output(self, output_file: Union[str, Path]) -> 'OpenSCADCommandBuilder':
        """
        Set output file path.
        
        Args:
            output_file: Path to output file
            
        Returns:
            self for method chaining
        """
        self.output_file = self._escape_value(output_file)
        return self
    
    def _escape_value(self, value: Union[str, Path]) -> str:
        """
        Platform-specific value escaping.
        
        Args:
            value: Value to escape
            
        Returns:
            str: Escaped value
        """
        str_value = str(value)
        if sys.platform == "win32":
            # PowerShell escaping rules
            if ' ' in str_value or '(' in str_value or ')' in str_value:
                return f"'{str_value}'"
            return str_value
        else:
            # POSIX shell escaping
            return f"'{str_value}'" if ' ' in str_value else str_value
    
    def build(self) -> List[str]:
        """
        Build the final command list.
        
        Returns:
            List[str]: Command parts ready for execution
            
        Raises:
            CommandError: If input or output file is not specified
        """
        if not self.input_file:
            raise CommandError("Input file must be specified")
        if not self.output_file:
            raise CommandError("Output file must be specified")
            
        return [
            str(self.openscad_path),
            *self.args,
            '-o', self.output_file,
            self.input_file
        ]

class OpenSCADCommandValidator:
    """
    Validates OpenSCAD commands and output formats.
    
    This class provides static methods for validating OpenSCAD commands,
    ensuring proper file formats and valid argument combinations.
    """
    
    # Supported export formats and their file extensions
    EXPORT_FORMATS: Final[Dict[str, ExportFormat]] = {
        'stl': {'extensions': ['.stl'], 'description': '3D model format'},
        'off': {'extensions': ['.off'], 'description': 'Object File Format'},
        'amf': {'extensions': ['.amf'], 'description': 'Additive Manufacturing Format'},
        '3mf': {'extensions': ['.3mf'], 'description': '3D Manufacturing Format'},
        'csg': {'extensions': ['.csg'], 'description': 'Constructive Solid Geometry'},
        'dxf': {'extensions': ['.dxf'], 'description': 'AutoCAD DXF'},
        'svg': {'extensions': ['.svg'], 'description': 'Scalable Vector Graphics'},
        'pdf': {'extensions': ['.pdf'], 'description': 'Portable Document Format'},
        'png': {'extensions': ['.png'], 'description': 'Portable Network Graphics'},
        'echo': {'extensions': ['.txt', '.echo'], 'description': 'Debug output'},
        'ast': {'extensions': ['.ast'], 'description': 'Abstract Syntax Tree'},
        'term': {'extensions': ['.term'], 'description': 'Terminal output'},
        'nef3': {'extensions': ['.nef3'], 'description': 'CGAL Nef polyhedron'},
        'nefdbg': {'extensions': ['.nefdbg'], 'description': 'CGAL Nef debug info'},
        'json': {'extensions': ['.json'], 'description': 'JSON format'}
    }

    # Valid command-line arguments and their allowed values
    VALID_ARGS: Final[Dict[str, Optional[Set[str]]]] = {
        '--render': None,  # No value needed
        '--preview': {'throwntogether', 'show-edges', 'show-axes', 'show-scales', 'show-crosshairs'},
        '--csglimit': None,  # Numeric value
        '--export-format': set(EXPORT_FORMATS.keys()),
        '--camera': None,  # Comma-separated values
        '--autocenter': None,  # No value needed
        '--viewall': None,  # No value needed
        '--imgsize': None,  # Numeric value
        '--projection': {'o', 'p'},  # Orthogonal or perspective
        '--colorscheme': {'Cornfield', 'Sunset', 'Metallic', 'Starnight', 'BeforeDawn', 'Nature', 'DeepOcean'},
        '--debug': {'none', 'echo', 'ast', 'term'},
        '--quiet': None,  # No value needed
        '--hardwarnings': None,  # No value needed
        '--check-parameters': {'true', 'false'},
        '--check-parameter-ranges': {'true', 'false'},
        '--info': None,  # No value needed
        '--help': None,  # No value needed
        '--version': None,  # No value needed
        '--backend': {'Manifold', 'CGAL', 'OpenCSG', 'Throw Together'},
    }

    @staticmethod
    def validate_output_format(output_file: Union[str, Path], export_format: Optional[str] = None) -> None:
        """
        Validate output file extension matches command arguments.
        
        Args:
            output_file: Path to output file
            export_format: Optional export format specified in command
            
        Raises:
            ValidationError: If output format is invalid or incompatible
        """
        output_path = Path(output_file)
        ext = output_path.suffix.lower()
        
        # If export format is specified, validate extension matches
        if export_format:
            if export_format not in OpenSCADCommandValidator.EXPORT_FORMATS:
                raise ValidationError(f"Invalid export format: {export_format}")
            
            valid_extensions = OpenSCADCommandValidator.EXPORT_FORMATS[export_format]['extensions']
            if ext not in valid_extensions:
                raise ValidationError(
                    f"Output file extension '{ext}' does not match export format '{export_format}'. "
                    f"Expected one of: {', '.join(valid_extensions)}"
                )
        else:
            # Without explicit format, validate extension is supported
            valid_extensions = {ext for fmt in OpenSCADCommandValidator.EXPORT_FORMATS.values() for ext in fmt['extensions']}
            if ext not in valid_extensions:
                raise ValidationError(
                    f"Unsupported output file extension: {ext}. "
                    f"Must be one of: {', '.join(sorted(valid_extensions))}"
                )

    @staticmethod
    def validate_input_file(input_file: Union[str, Path]) -> None:
        """
        Validate input file exists and has correct extension.
        
        Args:
            input_file: Path to input file
            
        Raises:
            ValidationError: If input file is invalid
            FileNotFoundError: If input file does not exist
        """
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        ext = input_path.suffix.lower()
        if ext not in {'.scad', '.stl', '.off', '.amf', '.3mf'}:
            raise ValidationError(
                f"Unsupported input file extension: {ext}. "
                "Must be one of: .scad, .stl, .off, .amf, .3mf"
            )

    @staticmethod
    def validate_arg(arg: str, value: Optional[str] = None) -> None:
        """
        Validate command-line argument and its value.
        
        Args:
            arg: Command-line argument
            value: Optional argument value
            
        Raises:
            ValidationError: If argument or value is invalid
        """
        if arg not in OpenSCADCommandValidator.VALID_ARGS:
            raise ValidationError(f"Invalid argument: {arg}")
        
        allowed_values = OpenSCADCommandValidator.VALID_ARGS[arg]
        if allowed_values is not None and value is not None:
            if value not in allowed_values:
                raise ValidationError(
                    f"Invalid value '{value}' for argument {arg}. "
                    f"Must be one of: {', '.join(sorted(allowed_values))}"
                )

    @staticmethod
    def validate_command(command: List[str]) -> None:
        """
        Validate complete OpenSCAD command.
        
        Args:
            command: List of command parts
            
        Raises:
            ValidationError: If command is invalid
            FileNotFoundError: If OpenSCAD executable not found
        """
        if not command:
            raise ValidationError("Empty command")
        
        openscad_path = command[0]
        if not os.path.exists(openscad_path):
            raise FileNotFoundError(f"OpenSCAD executable not found: {openscad_path}")
        
        # Track if we've seen input/output files
        has_input = False
        has_output = False
        export_format: Optional[str] = None
        output_file: Optional[str] = None
        
        i = 1
        while i < len(command):
            arg = command[i]
            
            # Handle -o/--output
            if arg in {'-o', '--output'}:
                if i + 1 >= len(command):
                    raise ValidationError(f"Missing value for {arg}")
                has_output = True
                output_file = command[i + 1]
                i += 2
                continue
            
            # Handle export format
            if arg == '--export-format':
                if i + 1 >= len(command):
                    raise ValidationError("Missing value for --export-format")
                export_format = command[i + 1]
                i += 2
                continue
            
            # Handle other arguments
            if arg.startswith('-'):
                if arg in OpenSCADCommandValidator.VALID_ARGS:
                    allowed_values = OpenSCADCommandValidator.VALID_ARGS[arg]
                    if allowed_values is not None and i + 1 < len(command):
                        OpenSCADCommandValidator.validate_arg(arg, command[i + 1])
                        i += 2
                    else:
                        i += 1
                else:
                    raise ValidationError(f"Invalid argument: {arg}")
            else:
                # Assume it's the input file
                has_input = True
                input_file = arg
                OpenSCADCommandValidator.validate_input_file(input_file)
                i += 1
        
        # Validate required parts
        if not has_input:
            raise ValidationError("No input file specified")
        if not has_output:
            raise ValidationError("No output file specified (-o/--output required)")
        
        # If export format specified, validate output extension
        if export_format and output_file:
            OpenSCADCommandValidator.validate_output_format(output_file, export_format)
