// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: l_bracket_plain
// fixture_type: l_bracket
// description: Plain L-bracket baseline for non-plate, non-box geometry.
$fn = 96;

bracket_size = [24.000000, 12.000000, 20.000000];
leg_thickness = 4.000000;
bracket_origin = [-12.000000, -6.000000, -10.000000];

union() {
  translate(bracket_origin) cube([bracket_size[0], bracket_size[1], leg_thickness]);
  translate(bracket_origin) cube([leg_thickness, bracket_size[1], bracket_size[2]]);
}
