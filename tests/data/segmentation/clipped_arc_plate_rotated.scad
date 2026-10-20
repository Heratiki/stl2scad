use <clipped_arc_plate.scad>
$fn = 64;
body_length = 40;
body_width = 20;
body_height = 10;
corner_1_radius = 3;
corner_2_radius = 3;
corner_3_radius = 3;
corner_4_radius = 3;
chamfer_1_width = 2;

rotate([17,31,9]) translate([-body_length/2,-body_width/2,-body_height/2])
    clipped_arc_plate(body_length,body_width,body_height,corner_1_radius,
        corner_2_radius,corner_3_radius,corner_4_radius,chamfer_1_width);
