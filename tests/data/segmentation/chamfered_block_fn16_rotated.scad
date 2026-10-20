use <chamfered_block.scad>
$fn = 16;
body_length = 60;
body_width = 40;
body_height = 8;
chamfer_1_width = 2;
chamfer_2_width = 2;

rotate([17,31,9]) translate([-body_length/2,-body_width/2,-body_height/2])
    chamfered_block(body_length,body_width,body_height,chamfer_1_width,chamfer_2_width);
