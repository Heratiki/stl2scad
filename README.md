# STL2SCAD

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://example.com)
[![Code Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen.svg)](https://example.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Overview

STL2SCAD is a Python-based tool designed to convert STL (Stereolithography) files into OpenSCAD (.scad) format. This conversion allows for easier manipulation and modification of 3D models within the OpenSCAD environment, enabling parametric design and customization. The tool provides both a command-line interface (CLI) and a graphical user interface (GUI) for flexibility and ease of use.

## Features

- **STL to OpenSCAD Conversion:** Accurately converts STL files to OpenSCAD format, preserving geometry and structure.
- **Optimization:** Offers options for mesh optimization to reduce complexity and improve performance in OpenSCAD.
- **Validation:** Performs validation checks on input STL files to ensure compatibility and identify potential issues.
- **Command-Line Interface (CLI):** Provides a powerful CLI for automated conversion and batch processing.
- **Graphical User Interface (GUI):** Offers an intuitive GUI for interactive use and visual preview.
- **OpenSCAD Integration:** Generates OpenSCAD code that is well-structured and easy to understand.
- **Preview Generation:** Integrates with OpenSCAD to provide visual previews of converted models.
- **Cross-Platform Support:** Works seamlessly on Windows, macOS, and Linux.

## Installation

### Prerequisites

- Python 3.7+
- OpenSCAD (for preview generation)

### Installation Steps

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/yourusername/stl2scad.git
    cd stl2scad
    ```

2.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

## Usage

### Command-Line Interface (CLI)

```bash
python stl2scad/cli.py <input_stl_file> [options]
```

**Options:**

-   `-o`, `--output`: Specify the output OpenSCAD file path (default: `<input_file>.scad`).
-   `-p`, `--preview`: Generate a preview image using OpenSCAD (requires OpenSCAD installation).
-   `--no-check`: Disable validation checks on the input STL file.
-   `--tolerance`: Set the tolerance for mesh simplification (default: 0.01).
-   `-v`, `--verbose`: Enable verbose output for debugging.
-   `-h`, `--help`: Show help message and exit.

**Example:**

```bash
python stl2scad/cli.py input.stl -o output.scad -p
```

### Graphical User Interface (GUI)

```bash
python stl2scad/gui/main_window.py
```

1.  Launch the GUI using the command above.
2.  Click the "Browse" button to select an STL file.
3.  (Optional) Adjust conversion settings as needed.
4.  Click the "Convert" button to start the conversion process.
5.  (Optional) Click "Preview" to generate a visual preview using OpenSCAD.

## Development

### Setting up the Development Environment

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/yourusername/stl2scad.git
    cd stl2scad
    ```

2.  **Create a virtual environment:**

    ```bash
    python3 -m venv venv
    ```

3.  **Activate the virtual environment:**

    -   **Windows:**

        ```bash
        venv\Scripts\activate
        ```

    -   **macOS/Linux:**

        ```bash
        source venv/bin/activate
        ```

4.  **Install development dependencies:**

    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt # Install additional development dependencies
    ```

### Running Tests

```bash
pytest
```

### Code Style

This project adheres to the following code style guidelines:

-   **PEP 8:** Follows the standard Python style guide.
-   **Black:** Uses the Black code formatter for consistent formatting.
-   **Pylint/Flake8:** Employs linters to enforce code quality and identify potential issues.
-   **MyPy:** Uses MyPy for static type checking.
-   **Type Hints:** All functions and methods should include type hints.

### Contributing

Contributions are welcome! Please follow these guidelines:

1.  Fork the repository.
2.  Create a new branch for your feature or bug fix: `git checkout -b feature/your-feature-name`.
3.  Make your changes and commit them with clear, descriptive messages.
4.  Ensure your code adheres to the project's code style guidelines.
5.  Run tests and ensure they pass.
6.  Submit a pull request to the `main` branch.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
