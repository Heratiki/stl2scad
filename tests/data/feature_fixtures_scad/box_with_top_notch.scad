// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: box_with_top_notch
// fixture_type: box
// description: Box with a rectangular notch cut from the top face. Documents that the conservative bounding-plane detector still classifies this as box_like_solid because the six outer boundary planes remain intact; interior cutouts are invisible to the current algorithm.
$fn = 96;

box_size = [24.000000, 16.000000, 12.000000];
box_origin = [-12.000000, -8.000000, -6.000000];

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
  translate([-4.000000, -4.000000, 0.000000]) cube([8.000000, 8.000000, 6.000000]);  // cutout_0
}
