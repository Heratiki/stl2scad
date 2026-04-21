// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: box_rounded_edges
// fixture_type: box
// description: Rounded-edge box with moderate fillets that preserve the axis-aligned cuboid envelope while reducing strict boundary-plane area.
$fn = 96;

box_size = [24.000000, 16.000000, 12.000000];
box_origin = [-12.000000, -8.000000, -6.000000];

edge_radius = 2.000000;
inner_box_size = [20.000000, 12.000000, 8.000000];

module rounded_box(size, r) {
  minkowski() {
    cube(size, center=true);
    sphere(r=r, $fn=48);
  }
}

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
  rounded_box(inner_box_size, edge_radius);
}
