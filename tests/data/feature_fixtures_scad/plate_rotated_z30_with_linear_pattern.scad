// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_rotated_z30_with_linear_pattern
// fixture_type: plate
// description: Plate rotated 30° around Z with three equally-spaced holes forming a linear pattern. Validates rotated-plate local-frame pattern detection.
// transform: rotate=[0.000000, 0.000000, 30.000000], translate=[0.000000, 0.000000, 0.000000]
$fn = 96;

plate_size = [30.000000, 12.000000, 2.000000];
plate_origin = [-15.000000, -6.000000, 0.000000];

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

translate([0.000000, 0.000000, 0.000000])
rotate([0.000000, 0.000000, 30.000000]) {
difference() {
  translate(plate_origin) cube(plate_size);
  through_hole([-8.000000, 0.000000, -0.100000], 3.000000, 2.200000);  // hole_0
  through_hole([0.000000, 0.000000, -0.100000], 3.000000, 2.200000);  // hole_1
  through_hole([8.000000, 0.000000, -0.100000], 3.000000, 2.200000);  // hole_2
}
}
