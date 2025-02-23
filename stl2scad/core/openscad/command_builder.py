"""
OpenSCAD command builder with platform-aware argument handling.
"""
import os
import sys
from pathlib import Path
from typing import List, Union

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
    
    @staticmethod
    def validate_output_format(output_file: Union[str, Path], expected_ext: str):
        """Validate output file extension matches command arguments."""
