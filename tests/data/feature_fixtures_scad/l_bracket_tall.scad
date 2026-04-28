// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: l_bracket_tall
// fixture_type: l_bracket
// description: Tall L-bracket (20x8x30 envelope, leg_thickness=3.5). High Z/X aspect ratio variant.
$fn = 96;

bracket_size = [20.000000, 8.000000, 30.000000];
leg_thickness = 3.500000;
bracket_origin = [-10.000000, -4.000000, -15.000000];

union() {
  translate(bracket_origin) cube([bracket_size[0], bracket_size[1], leg_thickness]);
  translate(bracket_origin) cube([leg_thickness, bracket_size[1], bracket_size[2]]);
}
