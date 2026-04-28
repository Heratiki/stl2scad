// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_rectangle_profile
// fixture_type: revolve
// description: Rectangle profile revolved around Z; Phase 2 → cylinder primitive upgrade.
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [5.000000, 0.000000],
    [5.000000, 10.000000],
    [0.000000, 10.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
