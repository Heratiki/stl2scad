// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_single_slot
// fixture_type: plate
// description: Single rounded slot in a compact plate.
$fn = 96;

plate_size = [18.000000, 8.000000, 2.000000];
plate_origin = [-9.000000, -4.000000, 0.000000];

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
  through_slot([-3.500000, 0.000000, -0.100000], [3.500000, 0.000000, -0.100000], 3.000000, 2.200000);  // slot_0
}
