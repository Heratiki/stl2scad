// Lower bar is rectangular; the head's two free-end corners round above it.
// Rib x bounds are its OUTER stadium bounds, including both half-round ends.
$fn = 64;
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

module stepped_bar(body_length=30, body_width=6, head_length=6,
                    step_1_height=2, step_2_height=10,
                    corner_1_radius=1, corner_2_radius=1,
                    corner_3_radius=0.5, corner_4_radius=0.5,
                    rib_start=4, rib_end=20) {
    r1=corner_1_radius; r2=corner_2_radius;
    q1=corner_3_radius; q2=corner_4_radius;
    assert(0<step_1_height && step_1_height<step_2_height);
    assert(min(body_length,body_width,head_length,r1,r2,q1,q2)>0);
    assert(max(r1,r2)<min(head_length,body_width/2));
    assert(rib_start>0 && rib_end<body_length-head_length);
    assert(q1+q2<rib_end-rib_start && 2*max(q1,q2)<body_width);
    union() {
        cube([body_length,body_width,step_1_height]);
        translate([0,0,step_1_height]) linear_extrude(height=step_2_height-step_1_height) {
            // Head: square west end and rounded east end.
            hull() {
                translate([body_length-head_length,0]) square([head_length-max(r1,r2),body_width]);
                translate([body_length-r1,r1]) circle(r=r1);
                translate([body_length-r2,body_width-r2]) circle(r=r2);
            }
            // Stadium: centers one radius in from the specified outer bounds.
            hull() {
                translate([rib_start+q1,body_width/2]) circle(r=q1);
                translate([rib_end-q2,body_width/2]) circle(r=q2);
            }
        }
    }
}

stepped_bar(body_length,body_width,head_length,step_1_height,step_2_height,
    corner_1_radius,corner_2_radius,corner_3_radius,corner_4_radius,rib_start,rib_end);
