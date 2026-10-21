// Hexagonal prism with chamfer on a non-orthogonal wall (T-006)
$fn = 6;
radius = 20;
height = 10;
chamfer_width = 2;
wall_angle = 0;

module hex_chamfer(radius=20, height=10, chamfer_width=2, wall_angle=0) {
    a = radius * cos(180 / 6);
    difference() {
        rotate([0, 0, 30]) cylinder(r=radius, h=height, $fn=6);
        rotate([0, 0, wall_angle]) rotate([90, 0, 0]) translate([0, 0, -30])
            linear_extrude(height=60)
                polygon([[a - chamfer_width, height],
                         [a + 1, height],
                         [a + 1, height - chamfer_width - 1]]);
    }
}

hex_chamfer(radius, height, chamfer_width, wall_angle);
