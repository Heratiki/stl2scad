// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_two_rectangular_pockets
// fixture_type: plate
// description: Two symmetrically placed rectangular blind pockets in a thick plate.
$fn = 96;

plate_size = [40.000000, 24.000000, 6.000000];
plate_origin = [-20.000000, -12.000000, 0.000000];

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

module rectangular_through_cutout(center, size_xy, plate_thickness) {
  translate([center[0] - size_xy[0] / 2, center[1] - size_xy[1] / 2, -0.1])
    cube([size_xy[0], size_xy[1], plate_thickness + 0.2]);
}

module rectangular_top_pocket(center, size_xy, pocket_depth, plate_thickness) {
  translate([center[0] - size_xy[0] / 2, center[1] - size_xy[1] / 2, plate_thickness - pocket_depth])
    cube([size_xy[0], size_xy[1], pocket_depth + 0.1]);
}

difference() {
  translate(plate_origin) cube(plate_size);
  rectangular_top_pocket([-10.000000, 0.000000, 0.000000], [10.000000, 8.000000], 3.000000, 6.000000);  // rectangular_pocket_0
  rectangular_top_pocket([10.000000, 0.000000, 0.000000], [10.000000, 8.000000], 3.000000, 6.000000);  // rectangular_pocket_1
}
