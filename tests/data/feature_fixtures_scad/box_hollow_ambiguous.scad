// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: box_hollow_ambiguous
// fixture_type: box
// description: Hollow box with interior cavity - can be interpreted as single hollow box OR as six separate wall plates
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
  translate([-7.000000, -3.000000, -1.000000]) cube([14.000000, 6.000000, 2.000000]);  // cutout_0
}
