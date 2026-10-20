use <stepped_bar.scad>
$fn = 16;
body_length = 30;
body_width = 6;
head_length = 6;
step_1_height = 2;
step_2_height = 10;
corner_1_radius = 1;
corner_2_radius = 1;
corner_3_radius = 0.5;
corner_4_radius = 0.5;
rib_start = 4;
rib_end = 20;

rotate([17,31,9]) translate([-body_length/2,-body_width/2,-step_2_height/2])
    stepped_bar(body_length,body_width,head_length,step_1_height,step_2_height,
        corner_1_radius,corner_2_radius,corner_3_radius,corner_4_radius,rib_start,rib_end);
