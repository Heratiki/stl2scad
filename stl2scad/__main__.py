"""
Main entry point for the STL to OpenSCAD converter.
"""

import sys
from PyQt5 import QtWidgets
from stl2scad.gui import MainWindow

def main():
    """Launch the GUI application."""
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
