// Source: tests/data/segmentation/rounded_plate_rotated.scad
// Gate limit: 0.0812145360446 mm; measured Hausdorff: 0.0000020993158685 mm
// Before snapping Hausdorff: 0.00000253009686947 mm
// How to edit: change Customizer parameters; host expressions move attached features.
// Assertions stop edits that violate linked dimensions. Distances are in mm.
/* [Body] */
// plate length (raw 60.0000001076)
plate_length = 60; // [0.01:0.01:120.000000215]
// plate width (raw 40.0000009568)
plate_width = 40; // [0.01:0.01:80.0000019136]
// plate thickness (raw 2.99999996955)
plate_thickness = 3; // [0.01:0.01:5.99999993909]
/* [Corner 1] */
// corner 1 radius (raw 4.99999976099)
corner_1_radius = 5; // [0.01:0.01:20.0000004784]
/* [Corner 2] */
// corner 2 radius (raw 4.99999947931)
corner_2_radius = 5; // [0.01:0.01:20.0000004784]
/* [Corner 3] */
// corner 3 radius (raw 4.99999973866)
corner_3_radius = 5; // [0.01:0.01:20.0000004784]
/* [Arc 1] */
// arc 1 radius (raw 4.00000001128)
arc_1_radius = 4; // [0.01:0.01:20.0000004784]
// arc 1 x (raw 29.9999994363)
arc_1_x = 30; // [-60.0000001076:0.01:120.000000215]
/* [Corner 4] */
// corner 4 radius (raw 4.99999978821)
corner_4_radius = 5; // [0.01:0.01:20.0000004784]
/* [Hole 1] */
// hole 1 x (raw 44.9999995432)
hole_1_x = 45; // [0:0.01:60.0000001076]
// hole 1 y (raw 30.0000008521)
hole_1_y = 30; // [0:0.01:40.0000009568]
// hole 1 diameter (raw 5.00000007469)
hole_1_diameter = 5; // [0.01:0.01:40.0000009568]
/* [Slot 1] */
// slot 1 x (raw 41.9999998091)
slot_1_x = 42; // [0:0.01:60.0000001076]
// slot 1 y (raw 14.0000007292)
slot_1_y = 14; // [0:0.01:40.0000009568]
// slot 1 width (raw 6.00000023036)
slot_1_width = 6; // [0.01:0.01:40.0000009568]
// slot 1 length (raw 16.0000000494)
slot_1_length = 16; // [0.01:0.01:72.1110261296]
// slot 1 angle (raw 0.00000105303786313)
slot_1_angle = 0; // [-180:0.01:180]
/* [Slot 2] */
// slot 2 x (raw 17.9999996484)
slot_2_x = 18; // [0:0.01:60.0000001076]
// slot 2 y (raw 24.0000004439)
slot_2_y = 24; // [0:0.01:40.0000009568]
// slot 2 width (raw 6.00000000133)
slot_2_width = 6; // [0.01:0.01:40.0000009568]
// slot 2 length (raw 16.0000000343)
slot_2_length = 16; // [0.01:0.01:72.1110261296]
// slot 2 angle (raw -29.9999990698)
slot_2_angle = -30; // [-180:0.01:180]
/* [Resolution] */
// corner 1 segments; a higher value gives a smoother part (raw 64)
corner_1_segments = 64; // [5:1:256]
// corner 2 segments; a higher value gives a smoother part (raw 64)
corner_2_segments = 64; // [5:1:256]
// corner 3 segments; a higher value gives a smoother part (raw 64)
corner_3_segments = 64; // [5:1:256]
// arc 1 segments; a higher value gives a smoother part (raw 64)
arc_1_segments = 64; // [5:1:256]
// corner 4 segments; a higher value gives a smoother part (raw 64)
corner_4_segments = 64; // [5:1:256]
// hole 1 segments; a higher value gives a smoother part (raw 64)
hole_1_segments = 64; // [5:1:256]
// slot 1 segments; a higher value gives a smoother part (raw 64)
slot_1_segments = 64; // [5:1:256]
// slot 2 segments; a higher value gives a smoother part (raw 64)
slot_2_segments = 64; // [5:1:256]
/* [Hidden] */
// End chords are clipped against the original regular polygon, not its incircle.
function _arc_point(c,r,a,phase,n) = let(s=360/n,m=phase+(floor((a-phase)/s)+0.5)*s,
    d=r*cos(s/2)/cos(a-m)) c+d*[cos(a),sin(a)];
function _arc(c,r,a,sweep,phase,n) = let(s=360/n,b=a+sweep,
    k0=floor((min(a,b)-phase)/s)+1,k1=ceil((max(a,b)-phase)/s)-1,
    v=k0<=k1 ? [for(k=[k0:k1]) c+r*[cos(phase+k*s),sin(phase+k*s)]] : [])
    concat([_arc_point(c,r,a,phase,n)],sweep>0?v:(len(v)?[for(i=[len(v)-1:-1:0]) v[i]]:[]),
           [_arc_point(c,r,b,phase,n)]);
function _cross(a,b) = a.x*b.y-a.y*b.x;
function _point_segment(p,a,b) = let(d=b-a,t=d*d>0?max(0,min(1,((p-a)*d)/(d*d))):0) norm(p-a-t*d);
function _segment_distance(a,b,c,d) =
    _cross(b-a,c-a)*_cross(b-a,d-a)<0 && _cross(d-c,a-c)*_cross(d-c,b-c)<0 ? 0 :
    min(_point_segment(a,c,d),_point_segment(b,c,d),_point_segment(c,a,b),_point_segment(d,a,b));
function _inside(p,poly) = len([for(i=[0:len(poly)-1]) let(a=poly[i],b=poly[(i+1)%len(poly)])
    if((a.y>p.y)!=(b.y>p.y)) if(p.x < (b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x) 1])%2 == 1;
function _capsule_inside(a,b,r,poly) = _inside((a+b)/2,poly) &&
    min([for(i=[0:len(poly)-1]) _segment_distance(a,b,poly[i],poly[(i+1)%len(poly)])]) > r;

_corner_1_start = _arc_point([corner_1_radius, corner_1_radius], corner_1_radius, 180, -101.250003882, corner_1_segments);
_corner_1_end = _arc_point([corner_1_radius, corner_1_radius], corner_1_radius, 270, -101.250003882, corner_1_segments);
_corner_2_start = _arc_point([plate_length-corner_2_radius, corner_2_radius], corner_2_radius, -90, -5.6249927909, corner_2_segments);
_corner_2_end = _arc_point([plate_length-corner_2_radius, corner_2_radius], corner_2_radius, 0, -5.6249927909, corner_2_segments);
_corner_3_start = _arc_point([plate_length-corner_3_radius, plate_width-corner_3_radius], corner_3_radius, 0, 84.3749960715, corner_3_segments);
_corner_3_end = _arc_point([plate_length-corner_3_radius, plate_width-corner_3_radius], corner_3_radius, 90, 84.3749960715, corner_3_segments);
_arc_1_start = _arc_point([arc_1_x, plate_width], arc_1_radius, 0, -174.375010936, arc_1_segments);
_arc_1_end = _arc_point([arc_1_x, plate_width], arc_1_radius, -180, -174.375010936, arc_1_segments);
_corner_4_start = _arc_point([corner_4_radius, plate_width-corner_4_radius], corner_4_radius, 90, 174.375008044, corner_4_segments);
_corner_4_end = _arc_point([corner_4_radius, plate_width-corner_4_radius], corner_4_radius, 180, 174.375008044, corner_4_segments);
_outline = concat(
  // face F0 corner_1 (cylinder)
  _arc([corner_1_radius, corner_1_radius], corner_1_radius, 180, 90, -101.250003882, corner_1_segments),
  // face F9 segment_2 (plane)
  [_corner_1_end, _corner_2_start],
  // face F8 corner_2 (cylinder)
  _arc([plate_length-corner_2_radius, corner_2_radius], corner_2_radius, -90, 90, -5.6249927909, corner_2_segments),
  // face F7 segment_4 (plane)
  [_corner_2_end, _corner_3_start],
  // face F6 corner_3 (cylinder)
  _arc([plate_length-corner_3_radius, plate_width-corner_3_radius], corner_3_radius, 0, 90, 84.3749960715, corner_3_segments),
  // face F5 segment_6 (plane)
  [_corner_3_end, _arc_1_start],
  // face F4 arc_1 (cylinder)
  _arc([arc_1_x, plate_width], arc_1_radius, 0, -180, -174.375010936, arc_1_segments),
  // face F3 segment_8 (plane)
  [_arc_1_end, _corner_4_start],
  // face F2 corner_4 (cylinder)
  _arc([corner_4_radius, plate_width-corner_4_radius], corner_4_radius, 90, 90, 174.375008044, corner_4_segments),
  // face F1 segment_10 (plane)
  [_corner_4_end, _corner_1_start]
);
_slot_1_start = [slot_1_x, slot_1_y]-((slot_1_length-slot_1_width)/2)*[cos(slot_1_angle),sin(slot_1_angle)];
_slot_1_end = [slot_1_x, slot_1_y]+((slot_1_length-slot_1_width)/2)*[cos(slot_1_angle),sin(slot_1_angle)];
_slot_2_start = [slot_2_x, slot_2_y]-((slot_2_length-slot_2_width)/2)*[cos(slot_2_angle),sin(slot_2_angle)];
_slot_2_end = [slot_2_x, slot_2_y]+((slot_2_length-slot_2_width)/2)*[cos(slot_2_angle),sin(slot_2_angle)];
assert(corner_1_radius < min(plate_length,plate_width)/2, "corner_1 must fit the available outline");
assert(corner_2_radius < min(plate_length,plate_width)/2, "corner_2 must fit the available outline");
assert(corner_3_radius < min(plate_length,plate_width)/2, "corner_3 must fit the available outline");
assert(arc_1_radius < min(plate_length,plate_width)/2, "arc_1 must fit the available outline");
assert(corner_4_radius < min(plate_length,plate_width)/2, "corner_4 must fit the available outline");
assert(_capsule_inside([hole_1_x,hole_1_y],[hole_1_x,hole_1_y],hole_1_diameter/2,_outline), "hole_1 must stay inside the outline");
assert(slot_1_length > slot_1_width, "slot_1 length must exceed its width");
assert(_capsule_inside(_slot_1_start,_slot_1_end,slot_1_width/2,_outline), "slot_1 must stay inside the outline");
assert(_segment_distance(_slot_1_start,_slot_1_end,[hole_1_x,hole_1_y],[hole_1_x,hole_1_y]) > (slot_1_width/2)+(hole_1_diameter/2), "slot_1 must not overlap hole_1");
assert(slot_2_length > slot_2_width, "slot_2 length must exceed its width");
assert(_capsule_inside(_slot_2_start,_slot_2_end,slot_2_width/2,_outline), "slot_2 must stay inside the outline");
assert(_segment_distance(_slot_2_start,_slot_2_end,[hole_1_x,hole_1_y],[hole_1_x,hole_1_y]) > (slot_2_width/2)+(hole_1_diameter/2), "slot_2 must not overlap hole_1");
assert(_segment_distance(_slot_2_start,_slot_2_end,_slot_1_start,_slot_1_end) > (slot_2_width/2)+(slot_1_width/2), "slot_2 must not overlap slot_1");
multmatrix([[-0.846614148178, -0.000870393273306, -0.532206469823, 26.2141417786], [-0.134090520714, 0.968087357371, 0.211722933933, -15.6566165478], [0.515038072729, 0.250611474027, -0.819713164909, -19.2338019309], [0, 0, 0, 1]])
linear_extrude(height=plate_thickness) difference() {
  // face F0 corner_1 (cylinder)
  // face F1 segment_10 (plane)
  // face F2 corner_4 (cylinder)
  // face F3 segment_8 (plane)
  // face F4 arc_1 (cylinder)
  // face F5 segment_6 (plane)
  // face F6 corner_3 (cylinder)
  // face F7 segment_4 (plane)
  // face F8 corner_2 (cylinder)
  // face F9 segment_2 (plane)
  // face F19 end_cap (plane)
  // face F20 end_cap (plane)
  polygon(points=_outline);
  // face F10 hole_1 (cylinder)
  translate([hole_1_x, hole_1_y]) rotate(-78.7499901138)
    circle(d=hole_1_diameter, $fn=hole_1_segments);
  // face F15 slot_1 (cylinder)
  // face F16 slot_1 (plane)
  // face F17 slot_1 (cylinder)
  // face F18 slot_1 (plane)
  hull() for(p=[_slot_1_start,_slot_1_end]) translate(p)
    rotate(-84.3750016743+slot_1_angle-(0.00000105303786313)) circle(d=slot_1_width, $fn=slot_1_segments);
  // face F11 slot_2 (cylinder)
  // face F12 slot_2 (plane)
  // face F13 slot_2 (cylinder)
  // face F14 slot_2 (plane)
  hull() for(p=[_slot_2_start,_slot_2_end]) translate(p)
    rotate(-80.6249986085+slot_2_angle-(-29.9999990698)) circle(d=slot_2_width, $fn=slot_2_segments);
}
