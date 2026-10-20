// Coarse rotated bracket; polygon vertices retain the true cylinder radii.
use <composite_bracket.scad>
$fn = 16;
rotate([17, 31, 9]) translate([-20, -15, -17.5]) composite_bracket();
