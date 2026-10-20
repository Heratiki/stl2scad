// Hand-written ground truth. Coordinates: [0,L] x [0,W] x [0,H].
$fn = 64;
body_length = 60;
body_width = 40;
body_height = 8;
chamfer_1_width = 2;
chamfer_2_width = 2;

module chamfered_block(body_length=60, body_width=40, body_height=8,
                       chamfer_1_width=2, chamfer_2_width=2) {
    assert(min(body_length,body_width,body_height)>0);
    assert(min(chamfer_1_width,chamfer_2_width)>0);
    assert(max(chamfer_1_width,chamfer_2_width)<body_height);
    assert(chamfer_1_width+chamfer_2_width<body_width);
    module along_x() {
        multmatrix([[0,0,1,-1],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
            linear_extrude(height=body_length+2) children();
    }
    difference() {
        cube([body_length,body_width,body_height]);
        along_x() polygon([[0,body_height],
            [chamfer_1_width,body_height],[0,body_height-chamfer_1_width]]);
        along_x() polygon([[body_width,body_height],
            [body_width-chamfer_2_width,body_height],
            [body_width,body_height-chamfer_2_width]]);
    }
}

chamfered_block(body_length,body_width,body_height,chamfer_1_width,chamfer_2_width);
