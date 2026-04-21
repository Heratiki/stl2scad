// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: plate_rectangular_through_cutout
// fixture_type: plate
// description: Plate with one axis-aligned rectangular through-cutout sized for conservative cuboid difference reconstruction.
$fn = 96;

plate_size = [28.000000, 18.000000, 4.000000];
plate_origin = [-14.000000, -9.000000, 0.000000];

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
  rectangular_through_cutout([0.000000, -3.000000, 0.000000], [6.000000, 4.000000], 4.000000);  // rectangular_cutout_0
}
