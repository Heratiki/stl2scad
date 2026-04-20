// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_grid_two_by_three
// fixture_type: plate
// description: Rectangular 2x3 hole grid for nested loop emission coverage.
$fn = 96;

plate_size = [20.000000, 12.000000, 2.000000];
plate_origin = [-10.000000, -6.000000, 0.000000];

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

difference() {
  translate(plate_origin) cube(plate_size);
  for (row = [0 : 1]) {
    for (col = [0 : 2]) {
      through_hole([-6.000000, -3.000000, -0.100000] + row * [0.000000, 6.000000, 0.000000] + col * [6.000000, 0.000000, 0.000000], 2.000000, 2.200000);  // grid_pattern_0
    }
  }
}
