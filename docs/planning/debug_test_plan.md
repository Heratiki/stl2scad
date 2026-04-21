# STL2SCAD Debug Feature Test Plan

## Progress Update (2025-02-23)

### Completed Items
- [x] Test basic OpenSCAD version check
  - Successfully detecting OpenSCAD 2025.02.19
  - Fixed UTF-8/UTF-16 encoding issues
- [x] Verify command execution with spaces in file paths
  - Implemented proper PowerShell path handling
- [x] Debug file generation partially working:
  - `*_debug.scad`: Successfully creating side-by-side comparison
  - `*_debug.echo`: Successfully generating console output

### Current Issues
1. Preview Generation
   - PNG preview not generating correctly
   - Need to investigate OpenSCAD preview command options
   - Current attempt using --preview=throwntogether

2. Analysis Generation
   - JSON analysis file not generating
   - Need to verify OpenSCAD export format options
   - Current attempt using --export-format json

### Next Steps
1. Test Organization
   - [x] Move test files to dedicated tests/ directory
   - [ ] Create separate test modules for different features
   - [ ] Add test configuration file

2. OpenSCAD Command Testing
   - [ ] Document working command options
   - [ ] Create test cases for each command type
   - [ ] Add error handling for common failures

3. File Generation
   - [ ] Fix PNG preview generation
   - [ ] Fix JSON analysis generation
   - [ ] Add validation for generated files

## Original Test Plan

### 1. OpenSCAD Command Execution Testing

#### PowerShell Command Tests
- [x] Test basic OpenSCAD version check
- [x] Verify command execution with spaces in file paths
- [ ] Test all OpenSCAD debug arguments:
  - `--backend=Manifold`
  - `--summary=all`
  - `--view=axes,edges,scales`
  - `--autocenter`
  - `--viewall`
  - `--colorscheme=Tomorrow Night`

#### Debug File Generation
- [ ] Verify all debug files are created:
  - [x] `*_debug.scad`: Side-by-side comparison
  - [ ] `*_analysis.json`: Geometry statistics
  - [x] `*_debug.echo`: OpenSCAD console output
  - [ ] `*_preview.png`: Visual preview
- [x] Check file cleanup functionality
- [ ] Validate file content format

[Rest of original plan remains unchanged...]

## Implementation Strategy (Updated)

1. ✓ Move tests to dedicated directory
2. ✓ Fix OpenSCAD version detection
3. → Fix preview and analysis generation
4. Implement measurement tools
5. Update documentation
6. Add automated validation
7. Enhance visualization features

## Success Criteria (Updated)

1. All debug files generate successfully
   - Current: 2/4 files working (SCAD and echo)
   - Need: PNG preview and JSON analysis
2. PowerShell commands work reliably
   - Current: Basic commands working
   - Need: Complex visualization commands
3. Visual comparison is clear and useful
4. Documentation is comprehensive
5. Automated tests pass
6. User feedback confirms improved usability