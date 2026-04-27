// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_annular_tube
// fixture_type: revolve
// description: Annular tube (inner r=3, outer r=6, height=10) revolved around Z; Phase 1.6 annular revolve.
$fn = 96;

profile = [
    [3.000000, 0.000000],
    [6.000000, 0.000000],
    [6.000000, 10.000000],
    [3.000000, 10.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
