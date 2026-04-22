// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: negative_hex_prism
// fixture_type: prism
// description: Hexagonal prism geometry as negative-class fixture to guard against cylinder over-detection.
$fn = 96;

radius = 10.000000;
height = 20.000000;
sides = 6;

cylinder(r=radius, h=height, $fn=sides);
