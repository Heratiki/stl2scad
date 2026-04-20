// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_long_aspect_linear
// fixture_type: plate
// description: High-aspect-ratio plate with a three-hole linear pattern.
$fn = 96;

plate_size = [60.000000, 12.000000, 2.000000];
plate_origin = [-30.000000, -6.000000, 0.000000];

module through_hole(center, diameter, height) {
  translate(center) cylinder(d=diameter, h=height, center=false);
}

module through_slot(start, end, width, height) {
  hull() {
    through_hole(start, width, height);
    through_hole(end, width, height);
  }
}

module counterbore_hole(center, through_d, bore_d, bore_depth, height) {
  translate(center) cylinder(d=through_d, h=height, center=false);
  translate([center[0], center[1], center[2] + height - bore_depth])
    cylinder(d=bore_d, h=bore_depth + 0.1, center=false);
}

difference() {
  translate(plate_origin) cube(plate_size);
  for (i = [0 : 2]) {
    through_hole([-18.000000, 0.000000, -0.100000] + i * [18.000000, 0.000000, 0.000000], 3.000000, 2.200000);  // linear_pattern_0
  }
}
