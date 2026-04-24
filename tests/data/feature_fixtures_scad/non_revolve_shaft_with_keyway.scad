// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: non_revolve_shaft_with_keyway
// fixture_type: non_revolve
// description: Near-axisymmetric shaft with one axial keyway slot.
$fn = 96;

diameter = 10.000000;
height = 20.000000;
keyway_width = 2.500000;
keyway_depth = 1.500000;

difference() {
    cylinder(h=height, d=diameter, center=false);
    translate([diameter/2 - keyway_depth, -keyway_width/2, height*0.2])
        cube([keyway_depth + 0.1, keyway_width, height*0.6]);
}
