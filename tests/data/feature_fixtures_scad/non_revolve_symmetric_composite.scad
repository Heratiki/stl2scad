// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: non_revolve_symmetric_composite
// fixture_type: non_revolve
// description: Plate with mirrored bosses; symmetric but not a revolve.
$fn = 96;

plate = [30.000000, 10.000000, 4.000000];

translate([-plate[0]/2, -plate[1]/2, 0]) cube(plate);
translate([9.000000, 0, 4.000000]) cylinder(h=2.000000, d=6.000000);
translate([-9.000000, 0, 4.000000]) cylinder(h=2.000000, d=6.000000);
