# STL2SCAD Tests

This directory contains the test suite for STL2SCAD. The tests are organized into different modules based on functionality.

## Test Structure

- `conftest.py`: Test configuration and fixtures
- `utils.py`: Common test utilities
- `pytest.ini`: Pytest configuration
- `data/`: Test data files (STL samples)
- Test modules:
  - `test_openscad.py`: OpenSCAD command execution tests
  - `test_conversion.py`: STL to SCAD conversion tests
  - `test_visualization.py`: Preview and analysis feature tests

## Running Tests

### Prerequisites

1. Install test dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Ensure OpenSCAD (Nightly) is installed and in the system PATH
   - Version 2025.02.19 or later required
   - Install from https://openscad.org/downloads.html#snapshots

### Running All Tests

```bash
pytest
```

### Running Specific Test Categories

```bash
# Run OpenSCAD-related tests
pytest tests/test_openscad.py

# Run conversion tests
pytest tests/test_conversion.py

# Run visualization tests
pytest tests/test_visualization.py
```

### Test Options

- Run tests in parallel:
  ```bash
  pytest -n auto
  ```

- Generate coverage report:
  ```bash
  pytest --cov=stl2scad
  ```

- Show local variables in failures:
  ```bash
  pytest --showlocals
  ```

## Test Plan Progress

See [debug_test_plan.md](debug_test_plan.md) for detailed test plan and progress tracking.

## Adding New Tests

1. Create test files in the appropriate module or create a new module if needed
2. Add fixtures to `conftest.py` if required
3. Add utility functions to `utils.py` if needed
4. Update `debug_test_plan.md` with new test cases
5. Add test data files to `data/` directory if needed

## Debugging Tests

- Tests are configured to stop on entry with VS Code debugger
- Use the "Python: Debug STL2SCAD" launch configuration
- Breakpoints and variable inspection are available
- Console output is captured and logged to test_run.log

## Common Issues

1. OpenSCAD Process Management
   - Tests check for lingering OpenSCAD processes
   - Processes are automatically terminated after tests
   - Use `check_openscad_processes()` to verify

2. File Encoding
   - OpenSCAD output files use UTF-8 encoding
   - Log files are written with timestamps
   - Use provided logging utilities

3. Test Data
   - Sample STL files are in `data/` directory
   - Test output goes to temporary directories
   - Files are cleaned up after tests