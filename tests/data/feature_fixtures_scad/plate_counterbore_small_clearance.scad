// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_counterbore_small_clearance
// fixture_type: plate
// description: Counterbore with very small radial clearance to the outer plate boundary.
$fn = 96;

plate_size = [44.000000, 24.000000, 6.000000];
plate_origin = [-22.000000, -12.000000, 0.000000];

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
  counterbore_hole([17.680000, 0.000000, 0.000000], 3.200000, 8.000000, 2.800000, 6.000000);  // counterbore_0
}
