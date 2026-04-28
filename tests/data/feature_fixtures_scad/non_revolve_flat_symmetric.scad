// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: non_revolve_flat_symmetric
// fixture_type: non_revolve
// description: Wide flat symmetric composite; symmetric but not a revolve, must be rejected.
$fn = 96;

plate = [40.000000, 12.000000, 3.000000];

translate([-plate[0]/2, -plate[1]/2, 0]) cube(plate);
translate([12.000000, 0, 3.000000]) cylinder(h=1.500000, d=8.000000);
translate([-12.000000, 0, 3.000000]) cylinder(h=1.500000, d=8.000000);
