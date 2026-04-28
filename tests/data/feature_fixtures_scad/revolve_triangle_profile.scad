// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_triangle_profile
// fixture_type: revolve
// description: Triangle profile revolved around Z; Phase 2 → cone primitive upgrade.
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [6.000000, 0.000000],
    [0.000000, 12.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
