// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: box_two_z_holes
// fixture_type: box
// description: Box with two z-axis through-holes offset symmetrically on X. Tests multi-hole counting.
$fn = 96;

box_size = [24.000000, 16.000000, 10.000000];
box_origin = [-12.000000, -8.000000, -5.000000];

module through_hole_x(center, diameter, length) {
  translate([box_origin[0] - 0.1, center[1], center[2]])
    rotate(a=90, v=[0, 1, 0]) cylinder(d=diameter, h=length, center=false);
}

module through_hole_y(center, diameter, length) {
  translate([center[0], box_origin[1] - 0.1, center[2]])
    rotate(a=90, v=[-1, 0, 0]) cylinder(d=diameter, h=length, center=false);
}

module through_hole_z(center, diameter, length) {
  translate([center[0], center[1], box_origin[2] - 0.1])
    cylinder(d=diameter, h=length, center=false);
}

difference() {
  translate(box_origin) cube(box_size);
  through_hole_z([-5.000000, 0.000000, 0.000000], 3.000000, 10.200000);  // hole_0
  through_hole_z([5.000000, 0.000000, 0.000000], 3.000000, 10.200000);  // hole_1
}
