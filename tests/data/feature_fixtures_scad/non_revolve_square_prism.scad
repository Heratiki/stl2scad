// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: non_revolve_square_prism
// fixture_type: non_revolve
// description: Square cross-section extruded along Z; cross-slice radial profiles differ by angle.
$fn = 96;

side = 10.000000;
height = 20.000000;

translate([-side/2, -side/2, 0]) linear_extrude(height) square(side);
