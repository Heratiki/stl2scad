// Composite bracket: ground truth for the segmentation pipeline.
// See docs/planning/segmentation_composite_bracket.md and composite_bracket_expected.json.
// Hand-written (not generated from the feature-fixture manifest).
$fn = 64;

module composite_bracket() {
    difference() {
        union() {
            cube([40, 30, 5]);                          // base
            cube([5, 30, 35]);                          // wall
            difference() {                              // R3 fillet, inner corner, axis Y
                translate([4, 0, 4]) cube([4, 30, 4]);
                translate([8, -1, 8]) rotate([-90, 0, 0]) cylinder(r = 3, h = 32);
            }
            translate([25, 15, 4]) cylinder(r = 6, h = 7);   // boss, top at z = 11
        }
        translate([34, 24, 2]) cylinder(r = 2.5, h = 4);     // blind hole, floor at z = 2
    }
}

composite_bracket();
