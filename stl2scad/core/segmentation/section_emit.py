"""Emit typed line/arc sketch paths and through cuts in a single part frame."""

import json
import math

from .. import ir


HELPERS = """/* [Hidden] */
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
"""


def geometry_scad(model):
    from .emit import _array, _number

    bindings = {id(b.node): b for b in model.bindings}
    extrusion = model.root.child.base
    if not isinstance(extrusion, ir.ExtrudeLinear) or not isinstance(
        extrusion.profile, ir.SketchPath2D
    ):
        raise ValueError("Expected an extruded typed sketch path")
    lines = [HELPERS]
    labels = {face: (label, kind) for face, label, kind in model.labels}

    def comments(node, pad=""):
        return [
            pad + f"// face {face} {labels[face][0]} ({labels[face][1]})"
            for face in node.face_ids
        ]

    parts = []

    def vector(point):
        if point[0].endswith("[0]") and point[1] == point[0][:-3] + "[1]":
            return point[0][:-3]
        return "[" + ", ".join(point) + "]"

    for segment in extrusion.profile.segments:
        binding = bindings[id(segment)]
        parts += comments(segment, "  ")
        if isinstance(segment, ir.SketchArc2D):
            for label, angle in [
                ("start", segment.start_deg),
                ("end", segment.start_deg + segment.sweep_deg),
            ]:
                lines.append(
                    f'_{binding.name}_{label} = _arc_point([{", ".join(binding.center[:2])}], {binding.name}_radius, {_number(angle)}, {_number(segment.phase_deg)}, {binding.name}_segments);'
                )
            args = ", ".join(
                [
                    "[" + ", ".join(binding.center[:2]) + "]",
                    binding.name + "_radius",
                    _number(segment.start_deg),
                    _number(segment.sweep_deg),
                    _number(segment.phase_deg),
                    binding.name + "_segments",
                ]
            )
            parts.append("  _arc(" + args + "),")
        elif isinstance(segment, ir.SketchLine2D):
            # Arc endpoints remain linked when a corner radius or plate
            # dimension changes. General lines expose both labeled endpoints.
            parts.append("  [" + ", ".join(vector(p) for p in binding.points) + "],")
        else:
            raise ValueError("Unsupported typed sketch segment")
    # Avoid a trailing argument comma (not accepted by older OpenSCAD).
    parts[-1] = parts[-1].removesuffix(",")
    lines += ["_outline = concat("] + parts + [");"]
    for node in model.root.child.cuts:
        b = bindings[id(node)]
        name = b.name
        if isinstance(node, ir.Slot):
            center = "[" + ", ".join(b.center[:2]) + "]"
            direction = f"(({name}_length-{name}_width)/2)*[cos({name}_angle),sin({name}_angle)]"
            lines += [
                f"_{name}_start = {center}-{direction};",
                f"_{name}_end = {center}+{direction};",
            ]
    lines += [
        f"assert({c.expression}, {json.dumps(c.message)});" for c in model.constraints
    ]
    lines += [
        "multmatrix(" + _array(model.root.matrix) + ")",
        "linear_extrude(height=plate_thickness) difference() {",
    ]
    lines += comments(extrusion, "  ") + ["  polygon(points=_outline);"]
    for node in model.root.child.cuts:
        b = bindings[id(node)]
        name = b.name
        lines += comments(node, "  ")
        if isinstance(node, ir.Slot):
            # phase is in the plate frame; slot angle changes rotate the end
            # polygons by the same delta, preserving their measured phase.
            measured = node.end[0] - node.start[0], node.end[1] - node.start[1]
            angle = (math.degrees(math.atan2(measured[1], measured[0])) + 90) % 180 - 90
            phase = f"{_number(b.phase_deg)}+{name}_angle-({_number(angle)})"
            lines += [
                f"  hull() for(p=[_{name}_start,_{name}_end]) translate(p)",
                f"    rotate({phase}) circle(d={name}_width, $fn={name}_segments);",
            ]
        elif isinstance(node, ir.HoleThrough):
            lines += [
                f'  translate([{", ".join(b.center[:2])}]) rotate({_number(b.phase_deg)})',
                f"    circle(d={name}_diameter, $fn={name}_segments);",
            ]
        else:
            raise ValueError("Unsupported typed through cut")
    return lines + ["}"]
