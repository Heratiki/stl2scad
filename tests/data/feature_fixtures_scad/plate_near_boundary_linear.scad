// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_near_boundary_linear
// fixture_type: plate
// description: Linear hole pair placed near the outer plate boundary without crossing it.
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

module counterbore_hole(center, through_d, bore_d, bore_depth, height) {
  translate(center) cylinder(d=through_d, h=height, center=false);
  translate([center[0], center[1], center[2] + height - bore_depth])
    cylinder(d=bore_d, h=bore_depth + 0.1, center=false);
}

difference() {
  translate(plate_origin) cube(plate_size);
  through_hole([-7.500000, 5.500000, -0.100000], 4.000000, 2.200000);  // hole_0
  through_hole([7.500000, 5.500000, -0.100000], 4.000000, 2.200000);  // hole_1
}
