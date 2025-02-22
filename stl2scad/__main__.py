"""
Main entry point for the STL to OpenSCAD converter.
"""

import sys

def main():
    """Launch either CLI or GUI mode based on arguments."""
    # If no arguments or --gui flag, launch GUI
    if len(sys.argv) == 1 or sys.argv[1] == '--gui':
        try:
            from PyQt5 import QtWidgets
            from stl2scad.gui import MainWindow
            app = QtWidgets.QApplication(sys.argv)
            window = MainWindow()
            window.show()
            sys.exit(app.exec_())
        except ImportError as e:
            print(f"Error: GUI dependencies not installed. {str(e)}", file=sys.stderr)
            sys.exit(1)
    else:
        # CLI mode
        from stl2scad.cli import main as cli_main
        cli_main()

if __name__ == "__main__":
    main()
