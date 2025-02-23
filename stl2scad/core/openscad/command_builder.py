"""
OpenSCAD command builder with platform-aware argument handling.
"""
import os
import sys
from pathlib import Path
from typing import List, Union, Dict, Set

class OpenSCADCommandBuilder:
    """Builds OpenSCAD commands with proper shell escaping."""
    
    def __init__(self, openscad_path: Union[str, Path]):
        self.openscad_path = Path(openscad_path)
        self.args: List[str] = []
        self.output_file: Union[str, Path, None] = None
        self.input_file: Union[str, Path, None] = None
        
    def add_arg(self, arg: str, value: Union[str, Path, None] = None) -> 'OpenSCADCommandBuilder':
        """Add a command-line argument with optional value."""
        self.args.append(arg)
        if value is not None:
            self.args.append(self._escape_value(value))
        return self
    
    def set_input(self, input_file: Union[str, Path]) -> 'OpenSCADCommandBuilder':
        """Set input SCAD file path."""
        self.input_file = self._escape_value(input_file)
        return self
    
    def set_output(self, output_file: Union[str, Path]) -> 'OpenSCADCommandBuilder':
        """Set output file path."""
        self.output_file = self._escape_value(output_file)
        return self
    
    def _escape_value(self, value: Union[str, Path]) -> str:
        """Platform-specific value escaping."""
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
        """Build the final command list."""
        if not self.input_file:
            raise ValueError("Input file must be specified")
        if not self.output_file:
            raise ValueError("Output file must be specified")
            
        return [
            str(self.openscad_path),
            *self.args,
            '-o', self.output_file,
            self.input_file
        ]

class OpenSCADCommandValidator:
    """Validates OpenSCAD commands and output formats."""
    
    # Supported export formats and their file extensions
    EXPORT_FORMATS = {
        'stl': ['.stl'],
        'off': ['.off'],
        'amf': ['.amf'],
        '3mf': ['.3mf'],
        'csg': ['.csg'],
        'dxf': ['.dxf'],
        'svg': ['.svg'],
        'pdf': ['.pdf'],
        'png': ['.png'],
        'echo': ['.txt', '.echo'],
        'ast': ['.ast'],
        'term': ['.term'],
        'nef3': ['.nef3'],
        'nefdbg': ['.nefdbg'],
        'json': ['.json']
    }

    # Valid command-line arguments and their allowed values
    VALID_ARGS = {
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
    def validate_output_format(output_file: Union[str, Path], export_format: str = None) -> None:
        """
        Validate output file extension matches command arguments.
        
        Args:
            output_file: Path to output file
            export_format: Optional export format specified in command
            
        Raises:
            ValueError: If output format is invalid or incompatible
        """
        output_path = Path(output_file)
        ext = output_path.suffix.lower()
        
        # If export format is specified, validate extension matches
        if export_format:
            if export_format not in OpenSCADCommandValidator.EXPORT_FORMATS:
                raise ValueError(f"Invalid export format: {export_format}")
            
            valid_extensions = OpenSCADCommandValidator.EXPORT_FORMATS[export_format]
            if ext not in valid_extensions:
                raise ValueError(
                    f"Output file extension '{ext}' does not match export format '{export_format}'. "
                    f"Expected one of: {', '.join(valid_extensions)}"
                )
        else:
            # Without explicit format, validate extension is supported
            valid_extensions = {ext for exts in OpenSCADCommandValidator.EXPORT_FORMATS.values() for ext in exts}
            if ext not in valid_extensions:
                raise ValueError(
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
            ValueError: If input file is invalid
            FileNotFoundError: If input file does not exist
        """
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        ext = input_path.suffix.lower()
        if ext not in {'.scad', '.stl', '.off', '.amf', '.3mf'}:
            raise ValueError(
                f"Unsupported input file extension: {ext}. "
                "Must be one of: .scad, .stl, .off, .amf, .3mf"
            )

    @staticmethod
    def validate_arg(arg: str, value: str = None) -> None:
        """
        Validate command-line argument and its value.
        
        Args:
            arg: Command-line argument
            value: Optional argument value
            
        Raises:
            ValueError: If argument or value is invalid
        """
        if arg not in OpenSCADCommandValidator.VALID_ARGS:
            raise ValueError(f"Invalid argument: {arg}")
        
        allowed_values = OpenSCADCommandValidator.VALID_ARGS[arg]
        if allowed_values is not None and value is not None:
            if value not in allowed_values:
                raise ValueError(
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
            ValueError: If command is invalid
        """
        if not command:
            raise ValueError("Empty command")
        
        openscad_path = command[0]
        if not os.path.exists(openscad_path):
            raise FileNotFoundError(f"OpenSCAD executable not found: {openscad_path}")
        
        # Track if we've seen input/output files
        has_input = False
        has_output = False
        export_format = None
        
        i = 1
        while i < len(command):
            arg = command[i]
            
            # Handle -o/--output
            if arg in {'-o', '--output'}:
                if i + 1 >= len(command):
                    raise ValueError(f"Missing value for {arg}")
                has_output = True
                output_file = command[i + 1]
                i += 2
                continue
            
            # Handle export format
            if arg == '--export-format':
                if i + 1 >= len(command):
                    raise ValueError("Missing value for --export-format")
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
                    raise ValueError(f"Invalid argument: {arg}")
            else:
                # Assume it's the input file
                has_input = True
                input_file = arg
                OpenSCADCommandValidator.validate_input_file(input_file)
                i += 1
        
        # Validate required parts
        if not has_input:
            raise ValueError("No input file specified")
        if not has_output:
            raise ValueError("No output file specified (-o/--output required)")
        
        # If export format specified, validate output extension
        if export_format:
            OpenSCADCommandValidator.validate_output_format(output_file, export_format)
