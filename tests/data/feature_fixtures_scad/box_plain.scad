// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: box_plain
// fixture_type: box
// description: Baseline plain box with no holes or cutouts. Simplest positive box_like_solid case.
$fn = 96;

box_size = [20.000000, 14.000000, 10.000000];
box_origin = [-10.000000, -7.000000, -5.000000];

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
}
