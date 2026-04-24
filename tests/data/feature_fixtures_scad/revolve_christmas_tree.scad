// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_christmas_tree
// fixture_type: revolve
// description: Sawtooth tree profile that should emit one compact rotate_extrude polygon.
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [2.000000, 0.800000],
    [4.000000, 2.200000],
    [2.800000, 3.400000],
    [5.000000, 4.800000],
    [3.200000, 6.000000],
    [6.000000, 7.400000],
    [0.000000, 9.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
