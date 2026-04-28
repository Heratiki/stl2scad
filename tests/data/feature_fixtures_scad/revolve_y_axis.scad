// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_y_axis
// fixture_type: revolve
// description: Rectangle profile revolved around Y axis; Phase 2 cylinder primitive upgrade.
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [4.000000, 0.000000],
    [4.000000, 12.000000],
    [0.000000, 12.000000]
];

rotate([-90, 0, 0]) rotate_extrude($fn=128) polygon(points=profile);
