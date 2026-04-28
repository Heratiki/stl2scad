// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_filleted_grid_holes
// fixture_type: plate
// description: Filleted-edge plate with a 2x2 hole grid. Combines edge fillet with grid detection.
$fn = 96;

plate_size = [28.000000, 16.000000, 2.000000];
plate_origin = [-14.000000, -8.000000, 0.000000];

module through_hole(center, diameter, height) {
  translate(center) cylinder(d=diameter, h=height, center=false);
}

module through_slot(start, end, width, height) {
  hull() {
    through_hole(start, width, height);
    through_hole(end, width, height);
  }
}

module counterbore_hole(center, through_d, bore_d, bore_depth, plate_thickness) {
  translate([center[0], center[1], -0.1])
    cylinder(d=through_d, h=plate_thickness + 0.2, center=false);
  translate([center[0], center[1], plate_thickness - bore_depth])
    cylinder(d=bore_d, h=bore_depth + 0.1, center=false);
}

plate_edge_radius = 1.000000;
plate_inner_square = [26.000000, 14.000000];

difference() {
  linear_extrude(height=plate_size[2]) offset(r=plate_edge_radius, $fn=48) square(plate_inner_square, center=true);
  for (row = [0 : 1]) {
    for (col = [0 : 1]) {
      through_hole([-5.000000, -5.000000, -0.100000] + row * [0.000000, 10.000000, 0.000000] + col * [10.000000, 0.000000, 0.000000], 2.000000, 2.200000);  // grid_pattern_0
    }
  }
}
