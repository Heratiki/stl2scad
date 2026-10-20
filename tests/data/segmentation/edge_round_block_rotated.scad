use <edge_round_block.scad>
$fn = 64;
body_length = 60;
body_width = 40;
body_height = 10;
edge_round_1_radius = 3;
chamfer_1_width = 1.5;

rotate([17,31,9]) translate([-body_length/2,-body_width/2,-body_height/2])
    edge_round_block(body_length,body_width,body_height,edge_round_1_radius,chamfer_1_width);
