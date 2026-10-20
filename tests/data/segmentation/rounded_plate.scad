// Independent, hand-written ground truth: rounds belong to the 2D outline.
// Overall slot length includes the two semicircular ends.
$fn = 64;

module rounded_plate() {
    linear_extrude(height=3) difference() {
        hull() for (x=[5,55], y=[5,35]) translate([x,y]) circle(r=5);
        translate([30,40]) circle(r=4); // concave semicircular outline notch
        translate([18,14]) hull() for (x=[-5,5]) translate([x,0]) circle(r=3);
        translate([42,24]) rotate(30)
            hull() for (x=[-5,5]) translate([x,0]) circle(r=3);
        translate([15,30]) circle(d=5);
    }
}

rounded_plate();
