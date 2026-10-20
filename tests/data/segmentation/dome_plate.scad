// Only the upper half of the ellipsoid is added, even when c exceeds H.
$fn = 64;
body_length = 60;
body_width = 40;
body_height = 4;
dome_1_a = 6;
dome_1_b = 4;
dome_1_c = 3;

module dome_plate(body_length=60, body_width=40, body_height=4,
                   dome_1_a=6, dome_1_b=4, dome_1_c=3) {
    assert(min(body_length,body_width,body_height,dome_1_a,dome_1_b,dome_1_c)>0);
    assert(2*dome_1_a<body_length && 2*dome_1_b<body_width);
    union() {
        cube([body_length,body_width,body_height]);
        translate([body_length/2,body_width/2,body_height]) intersection() {
            scale([dome_1_a,dome_1_b,dome_1_c]) sphere(r=1);
            translate([-dome_1_a,-dome_1_b,0])
                cube([2*dome_1_a,2*dome_1_b,dome_1_c]);
        }
    }
}

dome_plate(body_length,body_width,body_height,dome_1_a,dome_1_b,dome_1_c);
