// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: non_revolve_tall_box
// fixture_type: non_revolve
// description: Tall square-section prism; cross-slice radial profiles vary by angle, must be rejected as revolve.
$fn = 96;

side = 8.000000;
height = 40.000000;

translate([-side/2, -side/2, 0]) linear_extrude(height) square(side);
