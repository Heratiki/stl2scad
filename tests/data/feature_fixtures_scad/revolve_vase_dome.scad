// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_vase_dome
// fixture_type: revolve
// description: Complex vase-dome profile revolved around Z; no Phase 2 upgrade (curved non-primitive boundary).
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [4.000000, 1.000000],
    [5.000000, 3.000000],
    [4.500000, 6.000000],
    [3.000000, 8.500000],
    [0.000000, 9.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
