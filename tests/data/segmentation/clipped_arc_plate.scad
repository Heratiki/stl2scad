// The bottom-front cutter crosses both front XY corner arcs.
$fn = 64;
body_length = 40;
body_width = 20;
body_height = 10;
corner_1_radius = 3;
corner_2_radius = 3;
corner_3_radius = 3;
corner_4_radius = 3;
chamfer_1_width = 2;

module clipped_arc_plate(body_length=40, body_width=20, body_height=10,
                          corner_1_radius=3, corner_2_radius=3,
                          corner_3_radius=3, corner_4_radius=3, chamfer_1_width=2) {
    r1=corner_1_radius; r2=corner_2_radius;
    r3=corner_3_radius; r4=corner_4_radius;
    assert(min(body_length,body_width,body_height,r1,r2,r3,r4,chamfer_1_width)>0);
    assert(2*max(r1,r2,r3,r4)<min(body_length,body_width));
    assert(chamfer_1_width<min(body_width,body_height));
    difference() {
        linear_extrude(height=body_height) hull() {
            translate([r1,r1]) circle(r=r1);
            translate([body_length-r2,r2]) circle(r=r2);
            translate([body_length-r3,body_width-r3]) circle(r=r3);
            translate([r4,body_width-r4]) circle(r=r4);
        }
        multmatrix([[0,0,1,-1],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
            linear_extrude(height=body_length+2)
                polygon([[0,0],[chamfer_1_width,0],[0,chamfer_1_width]]);
    }
}

clipped_arc_plate(body_length,body_width,body_height,corner_1_radius,
    corner_2_radius,corner_3_radius,corner_4_radius,chamfer_1_width);
