use <dome_plate.scad>
$fn = 64;
body_length = 60;
body_width = 40;
body_height = 4;
dome_1_a = 28;
dome_1_b = 18;
dome_1_c = 10;

module dome_plate_large(body_length=60, body_width=40, body_height=4,
                         dome_1_a=28, dome_1_b=18, dome_1_c=10) {
    dome_plate(body_length,body_width,body_height,dome_1_a,dome_1_b,dome_1_c);
}

dome_plate_large(body_length,body_width,body_height,dome_1_a,dome_1_b,dome_1_c);
