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
            from PyQt5.QtCore import Qt
            from stl2scad.gui import MainWindow

            # Must be set before QApplication is constructed.
            # AA_EnableHighDpiScaling: auto-scales the UI based on monitor DPI.
            # AA_UseHighDpiPixmaps:    renders pixmaps at native resolution on HiDPI.
            QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

            # Allow fractional scale factors (150%, 175%, 200% etc.) to pass through
            # without rounding — avoids blurriness on non-integer DPI configs.
            try:
                QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
                    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
                )
            except AttributeError:
                pass  # Only available in PyQt5 >= 5.14

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
        sys.exit(cli_main())

if __name__ == "__main__":
    main()
