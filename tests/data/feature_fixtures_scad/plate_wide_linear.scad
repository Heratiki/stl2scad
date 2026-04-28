// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_wide_linear
// fixture_type: plate
// description: Wide plate with a 4-hole linear pattern along X. High-span pattern on a wide footprint.
$fn = 96;

plate_size = [60.000000, 20.000000, 2.000000];
plate_origin = [-30.000000, -10.000000, 0.000000];

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
  for (i = [0 : 3]) {
    through_hole([-21.000000, 0.000000, -0.100000] + i * [14.000000, 0.000000, 0.000000], 3.000000, 2.200000);  // linear_pattern_0
  }
}
