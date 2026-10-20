// Source: OpenSCAD_Model
// Gate limit: 0.0610327780787 mm; measured Hausdorff: 0.00000000013728103759 mm
// Before snapping Hausdorff: 0.000002826492865 mm
// How to edit: change Customizer parameters; host expressions move attached features.
// Assertions stop edits that violate linked dimensions. Distances are in mm.
/* [Body] */
// body width (raw 40)
body_width = 40; // [0.01:0.01:80]
// body height (raw 35)
body_height = 35; // [0.01:0.01:70]
// body depth (raw 30)
body_depth = 30; // [0.01:0.01:60]
// base thickness (raw 5)
base_thickness = 5; // [0.01:0.01:35]
// wall thickness (raw 5)
wall_thickness = 5; // [0.01:0.01:40]
/* [Fillet 1] */
// fillet 1 radius (raw 3.00000029096)
fillet_1_radius = 3; // [0.01:0.01:30]
/* [Boss 1] */
// boss 1 radius (raw 6.00000004198)
boss_1_radius = 6; // [0.01:0.01:14.99]
// boss 1 x (raw 15)
boss_1_x = 15; // [0:0.01:40]
// boss 1 z (raw 15.0000000972)
boss_1_z = 15; // [0:0.01:30]
// boss 1 height (raw 6)
boss_1_height = 6; // [0.01:0.01:40]
/* [Blind Hole 1] */
// blind hole 1 radius (raw 2.50000015651)
blind_hole_1_radius = 2.5; // [0.01:0.01:5.99]
// blind hole 1 x (raw 6.00000024015)
blind_hole_1_x = 6; // [0:0.01:40]
// blind hole 1 z (raw 24)
blind_hole_1_z = 24; // [0:0.01:30]
// blind hole 1 depth (raw 3)
blind_hole_1_depth = 3; // [0.01:0.01:4.99]
/* [Hidden] */
$fn = 64;
_join_epsilon = max(body_width, body_depth)*0.000001;
assert(base_thickness < body_height && wall_thickness < body_width, "Body legs must have positive free lengths");
assert(fillet_1_radius < body_width-wall_thickness && fillet_1_radius < body_height-base_thickness, "Fillet must fit between the free leg ends");
assert(boss_1_x > boss_1_radius && boss_1_x+boss_1_radius < body_width && boss_1_z > boss_1_radius && boss_1_z+boss_1_radius < body_depth, "Cylinder must stay inside the host footprint");
assert(boss_1_x+boss_1_radius+fillet_1_radius < body_width-wall_thickness, "Cylinder must clear the wall");
assert(blind_hole_1_depth < base_thickness, "Blind hole must leave a floor");
assert(blind_hole_1_x > blind_hole_1_radius && blind_hole_1_x+blind_hole_1_radius < body_width && blind_hole_1_z > blind_hole_1_radius && blind_hole_1_z+blind_hole_1_radius < body_depth, "Cylinder must stay inside the host footprint");
assert(blind_hole_1_x+blind_hole_1_radius+fillet_1_radius < body_width-wall_thickness, "Cylinder must clear the wall");
assert(body_width > 0 && body_height > 0 && body_depth > 0 && base_thickness > 0 && wall_thickness > 0 && fillet_1_radius > 0 && boss_1_radius > 0 && boss_1_height > 0 && blind_hole_1_radius > 0 && blind_hole_1_depth > 0, "Dimensions must stay positive");
assert(norm([boss_1_x-blind_hole_1_x, boss_1_z-blind_hole_1_z]) > boss_1_radius+blind_hole_1_radius, "Features on one host must not overlap");
multmatrix([[-1, 0, 0, 40], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
difference() {
  union() {
    // face F0 body_1_boundary (plane)
    // face F1 body_1_boundary (plane)
    // face F3 body_1_boundary (plane)
    // face F4 base_top (plane)
    // face F5 body_1_boundary (plane)
    // face F6 body_1_boundary (plane)
    // face F7 body_1_boundary (plane)
    // face F8 body_1_boundary (plane)
    // P0 = [0, 0]
    // P1 = [body_width, 0]
    // P2 = [body_width, body_height]
    // P3 = [body_width-wall_thickness, body_height]
    // P4 = [body_width-wall_thickness, base_thickness]
    // P5 = [0, base_thickness]
    linear_extrude(height=body_depth) polygon(points=[[0, 0], [body_width, 0], [body_width, body_height], [body_width-wall_thickness, body_height], [body_width-wall_thickness, base_thickness], [0, base_thickness]]);
    // face F2 fillet_1 (cylinder)
    linear_extrude(height=body_depth) difference() {
      polygon(points=[[(body_width-wall_thickness)+sign((body_width-wall_thickness)-(body_width-wall_thickness-fillet_1_radius))*_join_epsilon, (base_thickness)+sign((base_thickness)-(base_thickness+fillet_1_radius))*_join_epsilon], [body_width-wall_thickness-fillet_1_radius, (base_thickness)+sign((base_thickness)-(base_thickness+fillet_1_radius))*_join_epsilon], [body_width-wall_thickness-fillet_1_radius, base_thickness+fillet_1_radius], [(body_width-wall_thickness)+sign((body_width-wall_thickness)-(body_width-wall_thickness-fillet_1_radius))*_join_epsilon, base_thickness+fillet_1_radius]]);
      translate([body_width-wall_thickness-fillet_1_radius, base_thickness+fillet_1_radius]) circle(r=fillet_1_radius);
    }
    // face F9 boss_1_side (cylinder)
    // face F10 boss_1_cap (plane)
    translate([boss_1_x, (base_thickness)-(1)*_join_epsilon, boss_1_z]) rotate(a=90, v=[-1, 0, 0]) cylinder(r=boss_1_radius, h=boss_1_height+_join_epsilon);
  }
  // face F11 blind_hole_1_side (cylinder)
  // face F12 blind_hole_1_floor (plane)
  translate([blind_hole_1_x, (base_thickness)-(-1)*_join_epsilon, blind_hole_1_z]) rotate(a=90, v=[1, 0, 0]) cylinder(r=blind_hole_1_radius, h=blind_hole_1_depth+_join_epsilon);
}
