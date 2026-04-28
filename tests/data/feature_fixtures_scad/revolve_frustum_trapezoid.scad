// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: revolve_frustum_trapezoid
// fixture_type: revolve
// description: Trapezoidal frustum profile revolved around Z; Phase 2 cone primitive upgrade (r1=6, r2=3).
$fn = 96;

profile = [
    [0.000000, 0.000000],
    [6.000000, 0.000000],
    [3.000000, 10.000000],
    [0.000000, 10.000000]
];

rotate_extrude($fn=128) polygon(points=profile);
