// Rotated variant of composite_bracket.scad. The transform must match
// "variants" in composite_bracket_expected.json.
use <composite_bracket.scad>
$fn = 64;

rotate([17, 31, 9]) translate([-20, -15, -17.5]) composite_bracket();
