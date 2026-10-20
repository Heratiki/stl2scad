// R3 is a spatial convex round along X, not an XY profile corner.
$fn = 64;
body_length = 60;
body_width = 40;
body_height = 10;
edge_round_1_radius = 3;
chamfer_1_width = 1.5;

module edge_round_block(body_length=60, body_width=40, body_height=10,
                        edge_round_1_radius=3, chamfer_1_width=1.5) {
    r = edge_round_1_radius;
    w = chamfer_1_width;
    assert(min(body_length,body_width,body_height,r,w)>0);
    assert(max(r,w)<body_height && r+w<body_width);
    module along_x() {
        multmatrix([[0,0,1,-1],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
            linear_extrude(height=body_length+2) children();
    }
    difference() {
        cube([body_length,body_width,body_height]);
        along_x() difference() {
            translate([0,body_height-r]) square([r,r]);
            translate([r,body_height-r]) circle(r=r);
        }
        along_x() polygon([[body_width,body_height],
            [body_width-w,body_height],[body_width,body_height-w]]);
    }
}

edge_round_block(body_length,body_width,body_height,edge_round_1_radius,chamfer_1_width);
