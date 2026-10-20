// Unequal setbacks; this must never become a symmetric chamfer slider.
$fn = 64;
body_length = 60;
body_width = 40;
body_height = 8;
top_setback = 2;
front_setback = 4;

module asymmetric_chamfer_block(body_length=60, body_width=40, body_height=8,
                                 top_setback=2, front_setback=4) {
    assert(min(body_length,body_width,body_height,top_setback,front_setback)>0);
    assert(top_setback<body_width && front_setback<body_height);
    difference() {
        cube([body_length,body_width,body_height]);
        multmatrix([[0,0,1,-1],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
            linear_extrude(height=body_length+2)
                polygon([[0,body_height],[top_setback,body_height],
                         [0,body_height-front_setback]]);
    }
}

asymmetric_chamfer_block(body_length,body_width,body_height,top_setback,front_setback);
