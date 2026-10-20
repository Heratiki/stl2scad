"""Ray exits through an extruded polygon and scale-relative dimension limits."""

import numpy as np


def boundary_distance(first, second):
    """Symmetric vertex-to-boundary distance, invariant to line subdivision."""

    def directed(points, loop):
        a = loop[None, :, :]
        d = np.roll(loop, -1, axis=0)[None, :, :] - a
        den = np.sum(d * d, axis=2)
        t = np.clip(
            np.sum((points[:, None, :] - a) * d, axis=2)
            / np.maximum(den, np.finfo(float).tiny),
            0,
            1,
        )
        return (
            np.linalg.norm(points[:, None, :] - (a + t[:, :, None] * d), axis=2)
            .min(axis=1)
            .max()
        )

    return max(directed(first, second), directed(second, first))


def exclusive_limit(limit, value, scale):
    """Leave a positive margin without consuming the measured free space."""
    gap = float(limit - value)
    return float(limit - min(scale * 1e-6, max(gap, 0) / 2))


def material_depth(points, point, direction, height):
    """First positive boundary crossing along a ray into a polygon extrusion."""
    points, point, direction = map(
        lambda x: np.asarray(x, dtype=float), (points, point, direction)
    )
    tolerance = max(np.ptp(points, axis=0).max(), height) * 1e-8
    hits = []
    cross = lambda a, b: a[0] * b[1] - a[1] * b[0]
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        edge = b - a
        denominator = cross(direction[:2], edge)
        # For a CCW polygon cross(direction, edge) is its outward-normal
        # dot product. Entry hits must not become exits due to fitted noise.
        if denominator <= np.linalg.norm(edge) * 1e-12:
            continue
        t = cross(a - point[:2], edge) / denominator
        u = cross(a - point[:2], direction[:2]) / denominator
        if (
            t > tolerance
            and -1e-8 <= u <= 1 + 1e-8
            and -tolerance <= point[2] + t * direction[2] <= height + tolerance
        ):
            hits.append(t)
    if abs(direction[2]) > 1e-12:
        z = height if direction[2] > 0 else 0
        t = (z - point[2]) / direction[2]
        if t > tolerance:
            hits.append(t)
    if not hits:
        raise ValueError("Hole ray has no material exit")
    return float(min(hits))


PROFILE_DEPTH_SCAD = """// First exit through the current profile, including extrusion caps.
function _profile_cross(a,b) = a.x*b.y-a.y*b.x;
function _material_depth(p,d,poly,h) = let(eps=max(h,max([for(q=poly) norm(q)]))*1e-8,
    side=[for(i=[0:len(poly)-1]) let(a=poly[i],e=poly[(i+1)%len(poly)]-a,
        den=_profile_cross([d.x,d.y],e)) if(den>norm(e)*1e-12)
        let(t=_profile_cross(a-[p.x,p.y],e)/den,u=_profile_cross(a-[p.x,p.y],[d.x,d.y])/den)
        if(t>eps && u>=-1e-8 && u<=1+1e-8 && p.z+t*d.z>=-eps && p.z+t*d.z<=h+eps) t],
    caps=abs(d.z)>1e-12 ? [let(t=((d.z>0?h:0)-p.z)/d.z) if(t>eps) t] : [])
    min(concat(side,caps));
"""
