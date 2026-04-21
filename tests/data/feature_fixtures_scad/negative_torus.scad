// Auto-generated from tests/data/feature_fixtures_manifest.json
// fixture: negative_torus
// fixture_type: torus
// description: Torus geometry as negative-class fixture to guard against over-detection.
$fn = 96;

major_radius = 15.000000;
minor_radius = 5.000000;

module torus(major_r, minor_r) {
  rotate_extrude(convexity = 10, $fn = 96)
    translate([major_r, 0, 0])
      circle(r = minor_r, $fn = 64);
}

torus(major_radius, minor_radius);
