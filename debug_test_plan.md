# STL2SCAD Debug Feature Test Plan

## 1. OpenSCAD Command Execution Testing

### PowerShell Command Tests
- [ ] Test basic OpenSCAD version check
- [ ] Verify command execution with spaces in file paths
- [ ] Test all OpenSCAD debug arguments:
  - `--backend=Manifold`
  - `--summary=all`
  - `--view=axes,edges,scales`
  - `--autocenter`
  - `--viewall`
  - `--colorscheme=Tomorrow Night`

### Debug File Generation
- [ ] Verify all debug files are created:
  - `*_debug.scad`: Side-by-side comparison
  - `*_analysis.json`: Geometry statistics
  - `*_debug.echo`: OpenSCAD console output
  - `*_preview.png`: Visual preview
- [ ] Check file cleanup functionality
- [ ] Validate file content format

## 2. Geometry Comparison Features

### Visual Comparison
- [ ] Test side-by-side view rendering
- [ ] Verify measurement rulers visibility
- [ ] Check axes alignment between STL and SCAD
- [ ] Validate color scheme effectiveness

### Measurement Tools
- [ ] Add bounding box visualization
  ```openscad
  module show_bbox(points) {
    min_point = [min([for (p = points) p[0]]), min([for (p = points) p[1]]), min([for (p = points) p[2]])];
    max_point = [max([for (p = points) p[0]]), max([for (p = points) p[1]]), max([for (p = points) p[2]])];
    translate(min_point)
      %cube(max_point - min_point);
  }
  ```
- [ ] Implement dimension lines
  ```openscad
  module dimension_line(start, end, offset=5) {
    vector = end - start;
    length = norm(vector);
    translate(start)
      rotate([0, 0, atan2(vector[1], vector[0])])
        union() {
          cylinder(h=length, r=0.5, center=false);
          translate([0, offset, 0])
            text(str(length), size=5);
        }
  }
  ```

### Statistics and Analysis
- [ ] Verify vertex reduction calculation
- [ ] Test volume comparison
- [ ] Implement surface area comparison
- [ ] Add mesh quality metrics:
  - Triangle aspect ratio
  - Non-manifold edge detection
  - Hole detection

## 3. Documentation Updates

### README Updates
- [ ] Add debug feature overview
- [ ] Document OpenSCAD version requirements
- [ ] Provide debug file descriptions
- [ ] Include example usage with screenshots

### Debug Output Guide
- [ ] Create interpretation guide for:
  - Analysis JSON format
  - Echo output meaning
  - Visual comparison tips
- [ ] Add troubleshooting section
- [ ] Document common issues and solutions

## 4. Future Improvements

### Automated Testing
- [ ] Implement automated geometry validation
  - Compare vertex counts
  - Check face normals
  - Validate mesh integrity
- [ ] Add regression tests for conversion accuracy

### Enhanced Visualization
- [ ] Consider adding cross-section view
- [ ] Implement difference highlighting
- [ ] Add animation for rotation comparison

## Implementation Strategy

1. Start with OpenSCAD command testing as it's fundamental
2. Move to debug file generation verification
3. Implement new measurement tools
4. Update documentation
5. Add automated validation
6. Enhance visualization features

## Success Criteria

1. All debug files generate successfully
2. PowerShell commands work reliably
3. Visual comparison is clear and useful
4. Documentation is comprehensive
5. Automated tests pass
6. User feedback confirms improved usability