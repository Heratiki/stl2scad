// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_stepped_shaft
// fixture_type: revolve
// description: Stepped shaft profile for generic polygon revolve recovery.
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [3.000000, 0.500000],
    [3.500000, 2.000000],
    [5.000000, 3.500000],
    [5.500000, 5.000000],
    [4.000000, 7.000000],
    [3.000000, 9.000000],
    [0.000000, 10.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
