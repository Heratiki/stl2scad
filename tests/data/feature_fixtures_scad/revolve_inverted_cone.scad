// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_inverted_cone
// fixture_type: revolve
// description: Frustum (r1=2, r2=5, h=8) revolved around Z; tip-heavy taper; Phase 2 cone upgrade.
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [2.000000, 0.000000],
    [5.000000, 8.000000],
    [0.000000, 8.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
