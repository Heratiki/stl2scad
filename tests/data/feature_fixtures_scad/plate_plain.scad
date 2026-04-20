// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_plain
// fixture_type: plate
// description: Baseline plain plate with no cutouts.
$fn = 96;

plate_size = [20.000000, 10.000000, 2.000000];
plate_origin = [-10.000000, -5.000000, 0.000000];

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
}
