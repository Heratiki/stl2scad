// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_semicircle_profile
// fixture_type: revolve
// description: Semicircle-like profile revolved around Z; Phase 2 → sphere primitive upgrade.
$fn = 96;

profile = [
    [0.000000, -5.000000],
    [2.500000, -4.330127],
    [4.330127, -2.500000],
    [5.000000, 0.000000],
    [4.330127, 2.500000],
    [2.500000, 4.330127],
    [0.000000, 5.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
