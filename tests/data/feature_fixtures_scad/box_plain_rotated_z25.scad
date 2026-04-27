// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: box_plain_rotated_z25
// fixture_type: box
// description: Plain rotated box (no holes) to verify rotated-box detection — the simplest positive rotated-box case.
// transform: rotate=[0.000000, 0.000000, 25.000000], translate=[0.000000, 0.000000, 0.000000]
$fn = 96;

box_size = [18.000000, 12.000000, 10.000000];
box_origin = [-9.000000, -6.000000, -5.000000];

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

translate([0.000000, 0.000000, 0.000000])
rotate([0.000000, 0.000000, 25.000000]) {
difference() {
  translate(box_origin) cube(box_size);
}
}
