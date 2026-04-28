// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: l_bracket_wide
// fixture_type: l_bracket
// description: Wide L-bracket (30x10x20 envelope, leg_thickness=5.0). Wider Y extrusion depth variant.
$fn = 96;

bracket_size = [30.000000, 10.000000, 20.000000];
leg_thickness = 5.000000;
bracket_origin = [-15.000000, -5.000000, -10.000000];

union() {
  translate(bracket_origin) cube([bracket_size[0], bracket_size[1], leg_thickness]);
  translate(bracket_origin) cube([leg_thickness, bracket_size[1], bracket_size[2]]);
}
