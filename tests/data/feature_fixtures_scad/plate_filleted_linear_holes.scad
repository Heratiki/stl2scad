// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_filleted_linear_holes
// fixture_type: plate
// description: Filleted-edge plate with a two-hole linear pattern, combining edge fillet with repeated holes on a single plate.
$fn = 96;

plate_size = [24.000000, 14.000000, 2.000000];
plate_origin = [-12.000000, -7.000000, 0.000000];

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
plate_inner_square = [22.000000, 12.000000];

difference() {
  linear_extrude(height=plate_size[2]) offset(r=plate_edge_radius, $fn=48) square(plate_inner_square, center=true);
  through_hole([-4.000000, 0.000000, -0.100000], 4.000000, 2.200000);  // hole_0
  through_hole([4.000000, 0.000000, -0.100000], 4.000000, 2.200000);  // hole_1
}
