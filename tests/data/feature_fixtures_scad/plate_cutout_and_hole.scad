// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_cutout_and_hole
// fixture_type: plate
// description: Plate with one rectangular through-cutout and one separate round hole.
$fn = 96;

plate_size = [36.000000, 20.000000, 3.000000];
plate_origin = [-18.000000, -10.000000, 0.000000];

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
  through_hole([8.000000, 0.000000, -0.100000], 4.000000, 3.200000);  // hole_0
  rectangular_through_cutout([-8.000000, 0.000000, 0.000000], [8.000000, 8.000000], 3.000000);  // rectangular_cutout_0
}
