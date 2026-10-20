"""Survey real STL parts and draft independent segmentation ground truth.

Three subcommands:

  survey DIR            Triangle count, bbox and a simplicity estimate per STL.
  diagnose STL...       Run stl2scad.core.segmentation.segment_mesh and summarize it.
  draft STL --out JSON  Write a draft expected JSON (same schema as
                        tests/data/segmentation/composite_bracket_expected.json).

The draft ground truth is measured from the mesh with code in this file only
(normal clustering, plane offsets, circle fits on smooth patches, signed
dihedrals on shared edges). It does not import or call segment_mesh, so it is
an independent reference. It is a draft: a person must check it by hand.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from stl import mesh as stl_mesh

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Mesh loading (independent of stl2scad.core.segmentation.repair)
# ---------------------------------------------------------------------------


class Part:
    def __init__(self, path: Path):
        self.path = path
        tri = stl_mesh.Mesh.from_file(str(path)).vectors.astype(np.float64)
        self.tri = tri
        pts = tri.reshape(-1, 3)
        self.lo, self.hi = pts.min(0), pts.max(0)
        self.diag = float(np.linalg.norm(self.hi - self.lo))
        weld = max(self.diag * 1e-7, 1e-6)
        keys = np.round(pts / weld).astype(np.int64)
        _, first, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
        self.verts = pts[first]
        self.faces = inv.reshape(-1, 3)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        self.area = np.linalg.norm(n, axis=1) / 2
        self.normal = n / np.maximum(2 * self.area[:, None], 1e-300)
        self.centroid = tri.mean(1)
        edges = defaultdict(list)
        for t, (i, j, k) in enumerate(self.faces):
            for a, b in ((i, j), (j, k), (k, i)):
                edges[(min(a, b), max(a, b))].append((t, a, b))
        self.edges = edges
        self.bad_edges = sum(1 for v in edges.values() if len(v) != 2)
        self.volume = float(
            np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6
        )

    def signed_dihedral(self, t, u, a, b) -> float:
        """Degrees; + is convex. Edge a->b follows triangle t's winding."""
        d = self.verts[b] - self.verts[a]
        d /= np.linalg.norm(d)
        s = np.cross(self.normal[t], self.normal[u]) @ d
        c = self.normal[t] @ self.normal[u]
        return float(np.degrees(np.arctan2(s, c)))


# ---------------------------------------------------------------------------
# survey
# ---------------------------------------------------------------------------


def survey_one(path: Path) -> dict:
    p = Part(path)
    keep = p.area > 1e-12
    # Distinct plane directions carrying 95% of the area (1 degree buckets).
    n = p.normal[keep]
    w = p.area[keep]
    # Bucket normals on a ~1 degree grid (vectorized; approximate).
    _, inv = np.unique(np.round(n * 57.3).astype(np.int64), axis=0, return_inverse=True)
    rep_area = np.sort(np.bincount(inv.ravel(), weights=w))[::-1]
    dirs95 = int(np.searchsorted(np.cumsum(rep_area) / w.sum(), 0.95) + 1)
    axis_frac = float(w[np.abs(n).max(1) > np.cos(np.radians(1.0))].sum() / w.sum())
    # Simplicity: fewer triangles, fewer dominant directions, more axis-aligned area.
    score = np.log10(len(p.tri)) + 0.05 * dirs95 + 2.0 * (1 - axis_frac)
    return {
        "file": str(path),
        "triangles": len(p.tri),
        "bbox_mm": [round(float(x), 2) for x in (p.hi - p.lo)],
        "axis_aligned_area": round(axis_frac, 3),
        "directions_95pct_area": dirs95,
        "open_or_nonmanifold_edges": p.bad_edges,
        "complexity_score": round(float(score), 2),
    }


def cmd_survey(args) -> int:
    root = Path(args.input_dir)
    files = sorted(
        f for f in root.rglob("*") if f.suffix.lower() == ".stl" and f.is_file()
    )
    rows = []
    for f in files:
        try:
            row = survey_one(f)
        except Exception as exc:  # noqa: BLE001 - report and continue
            row = {"file": str(f), "error": repr(exc)}
        row["file"] = os.path.relpath(f, root)
        rows.append(row)
    rows.sort(key=lambda r: r.get("complexity_score", 1e9))
    for r in rows:
        if "error" in r:
            print(f"ERROR {r['file']}: {r['error']}")
            continue
        print(
            f"{r['complexity_score']:5.2f} {r['triangles']:7d} tris "
            f"bbox {r['bbox_mm']} axis {r['axis_aligned_area']:.2f} "
            f"dirs95 {r['directions_95pct_area']:3d}  {r['file']}"
        )
    if args.output:
        Path(args.output).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# diagnose (calls the pipeline under test)
# ---------------------------------------------------------------------------


def diagnose_one(path: Path, min_area: float) -> dict:
    from stl2scad.core.segmentation import segment_mesh

    m = stl_mesh.Mesh.from_file(str(path))
    out = {"file": str(path), "triangles": len(m.vectors)}
    t0 = time.perf_counter()
    try:
        res = segment_mesh(m)
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        out["runtime_s"] = round(time.perf_counter() - t0, 2)
        out["exception"] = repr(exc)
        return out
    out["runtime_s"] = round(time.perf_counter() - t0, 2)
    v = m.vectors.astype(np.float64)
    tri_area = np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1) / 2
    kinds = defaultdict(int)
    big = defaultdict(int)
    cyl = []
    for f in res.faces:
        kinds[f.kind] += 1
        a = float(tri_area[list(f.triangle_indices)].sum())
        if a >= min_area:
            big[f.kind] += 1
        if f.kind == "cylinder":
            cyl.append(
                {
                    "id": f.id,
                    "radius": round(float(f.params.radius), 3),
                    "axis": [round(float(x), 3) for x in f.params.axis],
                    "convexity": f.convexity,
                    "area": round(a, 2),
                }
            )
    conv = defaultdict(int)
    for _, _, d in res.graph.edges(data=True):
        conv[d["convexity"]] += 1
    out.update(
        faces=dict(kinds),
        faces_area_ge_min=dict(big),
        cylinders=sorted(cyl, key=lambda c: -c["area"]),
        edges=dict(conv),
    )
    return out


def cmd_diagnose(args) -> int:
    rows = [diagnose_one(Path(f), args.min_area) for f in args.stl]
    print(json.dumps(rows, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# draft (independent measurement)
# ---------------------------------------------------------------------------


def _components(n_items, pairs):
    parent = list(range(n_items))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups = defaultdict(list)
    for i in range(n_items):
        groups[find(i)].append(i)
    return list(groups.values())


def _fit_circle(points2d):
    x, y = points2d[:, 0], points2d[:, 1]
    a = np.c_[2 * x, 2 * y, np.ones_like(x)]
    sol = np.linalg.lstsq(a, x * x + y * y, rcond=None)[0]
    r = float(np.sqrt(sol[2] + sol[0] ** 2 + sol[1] ** 2))
    res = np.abs(np.hypot(x - sol[0], y - sol[1]) - r)
    return sol[:2], r, float(res.max())


def measure(part: Part, min_area: float, plane_tol: float):
    """Return (faces, owner) measured independently from the mesh."""
    n_tri = len(part.tri)
    flat_pairs, smooth_pairs = [], []
    for ts in part.edges.values():
        if len(ts) != 2:
            continue
        (t, a, b), (u, _, _) = ts
        ang = np.degrees(np.arccos(np.clip(part.normal[t] @ part.normal[u], -1, 1)))
        if ang < 0.5:
            flat_pairs.append((t, u))
        elif ang < 40.0:
            smooth_pairs.append((t, u))

    # Planar regions: connected, same normal, same offset.
    planes = []
    for comp in _components(n_tri, flat_pairs):
        comp = np.array(comp)
        w = part.area[comp]
        if w.sum() <= 0:
            continue
        nrm = (part.normal[comp] * w[:, None]).sum(0)
        nrm /= np.linalg.norm(nrm)
        off = float((part.centroid[comp] @ nrm * w).sum() / w.sum())
        spread = float(np.abs(part.tri[comp].reshape(-1, 3) @ nrm - off).max())
        planes.append((comp, nrm, off, float(w.sum()), spread))
    # A planar region that is a facet of a tessellated curve is a narrow strip
    # between two or more parallel smooth creases. Mark those as curved.
    region = np.full(n_tri, -1)
    for r, (comp, *_rest) in enumerate(planes):
        region[comp] = r
    creases = defaultdict(list)
    for ts in part.edges.values():
        if len(ts) != 2:
            continue
        (t, a, b), (u, _, _) = ts
        ra, rb = region[t], region[u]
        if ra == rb:
            continue
        ang = np.degrees(np.arccos(np.clip(part.normal[t] @ part.normal[u], -1, 1)))
        if ang < 40.0:
            d = part.verts[b] - part.verts[a]
            mid = (part.verts[a] + part.verts[b]) / 2
            creases[ra].append((d, mid))
            creases[rb].append((d, mid))
    facet = set()
    for r, lst in creases.items():
        if len(lst) < 2:
            continue
        nrm = planes[r][1]
        dirs = np.array([d / np.linalg.norm(d) for d, _ in lst])
        lens = np.array([np.linalg.norm(d) for d, _ in lst])
        main = dirs[np.argmax(lens)]
        if np.min(np.abs(dirs @ main)) < np.cos(np.radians(5.0)):
            continue
        across = np.cross(nrm, main)
        mids = np.array([m for _, m in lst]) @ across
        width = mids.max() - mids.min()
        if 0 < width < 0.05 * part.diag:
            facet.add(r)

    owner = np.full(n_tri, -1)
    faces = []
    for r, (comp, nrm, off, area, spread) in enumerate(planes):
        if r in facet:
            continue
        if area >= min_area and spread <= plane_tol:
            owner[comp] = len(faces)
            pt = part.centroid[comp][np.argmax(part.area[comp])]
            faces.append(
                {
                    "kind": "plane",
                    "normal": nrm,
                    "point": pt,
                    "area": area,
                    "tris": comp,
                }
            )

    # Curved regions: smooth patches over triangles not in a large plane.
    free = owner < 0
    pairs = [(t, u) for t, u in smooth_pairs + flat_pairs if free[t] and free[u]]
    for comp in _components(n_tri, pairs):
        comp = np.array(comp)
        if not free[comp[0]] or len(comp) < 4:
            continue
        w = part.area[comp]
        if w.sum() < min_area:
            continue
        nrm = part.normal[comp]
        evals, evecs = np.linalg.eigh((nrm * w[:, None]).T @ nrm)
        axis = evecs[:, 0]
        if evals[0] / max(evals.sum(), 1e-12) > 0.02:
            faces.append({"kind": "freeform", "area": float(w.sum()), "tris": comp})
            owner[comp] = len(faces) - 1
            continue
        u1 = np.cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0])
        u1 /= np.linalg.norm(u1)
        u2 = np.cross(axis, u1)
        pts = part.tri[comp].reshape(-1, 3)
        c2, r, res = _fit_circle(np.c_[pts @ u1, pts @ u2])
        center = c2[0] * u1 + c2[1] * u2
        h = pts @ axis
        radial = part.centroid[comp] - center
        radial -= np.outer(radial @ axis, axis)
        conv = float(np.sign(np.einsum("ij,ij->i", radial, nrm)) @ w / w.sum())
        ang = np.sort(np.arctan2(pts @ u2 - c2[1], pts @ u1 - c2[0]))
        gaps = np.diff(np.r_[ang, ang[0] + 2 * np.pi])
        sweep = float(np.degrees(2 * np.pi - gaps.max()))
        faces.append(
            {
                "kind": "cylinder" if res <= max(0.05 * r, 0.02) else "freeform",
                "axis": axis,
                "point": center + axis * h.min(),
                "radius": r,
                "fit_max_residual": res,
                "length": float(h.max() - h.min()),
                "sweep_deg": sweep,
                "convexity": "convex" if conv > 0 else "concave",
                "area": float(w.sum()),
                "tris": comp,
            }
        )
        owner[comp] = len(faces) - 1
    return faces, owner


def measure_edges(part: Part, owner, faces, tangent_deg=7.5):
    ev = defaultdict(list)
    for ts in part.edges.values():
        if len(ts) != 2:
            continue
        (t, a, b), (u, _, _) = ts
        fa, fb = int(owner[t]), int(owner[u])
        if fa < 0 or fb < 0 or fa == fb:
            continue
        length = float(np.linalg.norm(part.verts[b] - part.verts[a]))
        ang = part.signed_dihedral(t, u, a, b)
        ev[(min(fa, fb), max(fa, fb))].append((ang, length))
    out = {}
    for k, lst in ev.items():
        angs = np.array([x for x, _ in lst])
        lens = np.array([y for _, y in lst])
        signed = float(np.average(angs, weights=lens))
        if np.abs(angs).max() <= tangent_deg:
            c = "tangent"
        else:
            c = "convex" if signed > 0 else "concave"
        out[k] = {"convexity": c, "signed_deg": signed, "length": float(lens.sum())}
    return out


def _r(x, nd=3):
    return [round(float(v), nd) + 0.0 for v in x]


def draft_features(faces, edges, names):
    feats = []
    nbrs = defaultdict(dict)
    for (a, b), e in edges.items():
        nbrs[a][b] = e
        nbrs[b][a] = e
    counters = defaultdict(int)
    slot_ends = []
    for i, f in enumerate(faces):
        if f["kind"] != "cylinder":
            continue
        ax = f["axis"]
        caps = [
            j
            for j in nbrs[i]
            if faces[j]["kind"] == "plane" and abs(faces[j]["normal"] @ ax) > 0.999
        ]
        sides = [
            j
            for j, e in nbrs[i].items()
            if faces[j]["kind"] == "plane"
            and abs(faces[j]["normal"] @ ax) < 0.02
            and e["convexity"] == "tangent"
        ]
        f_conv = f["convexity"]
        if f_conv == "concave" and len(sides) >= 2 and 170 <= f["sweep_deg"] <= 190:
            floors = [j for j in caps if nbrs[i][j]["convexity"] == "concave"]
            slot_ends.append((i, frozenset(sides), floors))
            continue
        if len(sides) >= 2 and f["sweep_deg"] < 170:
            kind = "fillet" if f_conv == "concave" else "edge_round"
            feat = {
                "kind": kind,
                "polarity": "additive" if kind == "fillet" else "subtractive",
                "radius": round(f["radius"], 3),
                "between": [names[j] for j in sides[:2]],
            }
        elif f_conv == "concave":
            floors = [j for j in caps if nbrs[i][j]["convexity"] == "concave"]
            mouths = [j for j in caps if nbrs[i][j]["convexity"] == "convex"]
            if floors:
                kind = "blind_hole"
                feat = {"kind": kind, "polarity": "subtractive",
                        "radius": round(f["radius"], 3),
                        "depth": round(f["length"], 3),
                        "on_face": names[mouths[0]] if mouths else None}
            else:
                kind = "through_hole" if f["sweep_deg"] > 300 else "concave_arc"
                feat = {"kind": kind, "polarity": "subtractive",
                        "radius": round(f["radius"], 3),
                        "length": round(f["length"], 3)}
        else:
            foot = [j for j in caps if nbrs[i][j]["convexity"] == "concave"]
            if foot and f["sweep_deg"] > 300:
                kind = "boss"
                feat = {"kind": kind, "polarity": "additive",
                        "radius": round(f["radius"], 3),
                        "height": round(f["length"], 3),
                        "on_face": names[foot[0]]}
            else:
                kind = "convex_arc"
                feat = {"kind": kind, "polarity": "additive",
                        "radius": round(f["radius"], 3),
                        "length": round(f["length"], 3),
                        "sweep_deg": round(f["sweep_deg"], 1)}
        counters[kind] += 1
        feat["id"] = f"{kind}_{counters[kind]}"
        if kind == "boss":
            own = [j for j in caps if nbrs[i][j]["convexity"] == "convex"]
        elif kind == "blind_hole":
            own = [j for j in caps if nbrs[i][j]["convexity"] == "concave"]
        else:
            own = []
        feat["faces"] = [names[i]] + [names[j] for j in own]
        feats.append(feat)
    # Pair half-cylinder ends that share the same two straight walls: a slot.
    used = set()
    for a, (i, walls, floors) in enumerate(slot_ends):
        for b in range(a + 1, len(slot_ends)):
            j, walls_j, floors_j = slot_ends[b]
            if a in used or b in used or len(walls & walls_j) < 2:
                continue
            used |= {a, b}
            fi, fj = faces[i], faces[j]
            d = fj["point"] - fi["point"]
            d -= (d @ fi["axis"]) * fi["axis"]
            kind = "blind_slot" if floors or floors_j else "through_slot"
            counters[kind] += 1
            feat = {
                "id": f"{kind}_{counters[kind]}",
                "kind": kind,
                "polarity": "subtractive",
                "width": round(2 * fi["radius"], 3),
                "length": round(float(np.linalg.norm(d)) + 2 * fi["radius"], 3),
                "depth": round(fi["length"], 3),
                "end_radius": round(fi["radius"], 3),
                "faces": [names[i], names[j]]
                + [names[w] for w in sorted(walls & walls_j)]
                + [names[w] for w in sorted(set(floors) | set(floors_j))],
            }
            feats.append(feat)
    for a, (i, walls, floors) in enumerate(slot_ends):
        if a not in used:
            counters["concave_arc"] += 1
            feats.append({
                "id": f"concave_arc_{counters['concave_arc']}",
                "kind": "concave_arc", "polarity": "subtractive",
                "radius": round(faces[i]["radius"], 3),
                "sweep_deg": round(faces[i]["sweep_deg"], 1),
                "faces": [names[i]],
            })
    return feats


def cmd_draft(args) -> int:
    path = Path(args.stl).resolve()
    part = Part(path)
    min_area = args.min_area if args.min_area else 0.25
    plane_tol = max(0.01, 2e-4 * part.diag)
    faces, owner = measure(part, min_area, plane_tol)
    edges = measure_edges(part, owner, faces)
    names = []
    for i, f in enumerate(faces):
        names.append(f"{f['kind'][0].upper()}{i}")
    out_faces = []
    unexplained = 0.0
    for i, f in enumerate(faces):
        if f["kind"] == "freeform":
            unexplained += f["area"]
            continue
        d = {"id": names[i], "kind": f["kind"]}
        if f["kind"] == "plane":
            d.update(normal=_r(f["normal"], 4), point=_r(f["point"]))
        else:
            d.update(
                axis=_r(f["axis"], 4), point=_r(f["point"]),
                radius=round(f["radius"], 3), convexity=f["convexity"],
                length=round(f["length"], 3), sweep_deg=round(f["sweep_deg"], 1),
                fit_max_residual_mm=round(f["fit_max_residual"], 4),
            )
        d["area_mm2"] = round(f["area"], 2)
        out_faces.append(d)
    kept = {names[i] for i, f in enumerate(faces) if f["kind"] != "freeform"}
    out_edges = [
        {"faces": [names[a], names[b]], "convexity": e["convexity"],
         "length_mm": round(e["length"], 2)}
        for (a, b), e in sorted(edges.items())
        if names[a] in kept and names[b] in kept
    ]
    try:
        src = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        src = path.as_posix()
    total = float(part.area.sum())
    covered = sum(f["area"] for f in faces if f["kind"] != "freeform")
    doc = {
        "status": "draft - needs hand check",
        "description": (
            f"Draft ground truth for {path.name}. Measured by "
            "scripts/survey_real_parts.py draft (normal clustering, circle fits, "
            "signed dihedrals); not copied from segment_mesh. Plane normals point "
            "out of the material. Coordinates are in the STL frame. Faces smaller "
            f"than {min_area:.2f} mm^2 are omitted."
        ),
        "source_stl": src,
        "units": "mm",
        "triangles": len(part.tri),
        "bbox_min": _r(part.lo),
        "bbox_max": _r(part.hi),
        "volume_mm3": round(part.volume, 3),
        "surface_area_mm2": round(total, 2),
        "area_covered_by_listed_faces": round(covered / total, 4),
        "area_freeform_or_unfitted_mm2": round(total - covered, 2),
        "hausdorff_max_mm": round(max(0.05, 0.001 * part.diag), 4),
        "tolerances": {
            "plane_normal_deg": 1.0,
            "plane_offset_mm": 0.05,
            "cylinder_axis_deg": 1.0,
            "cylinder_radius_rel": 0.02,
            "volume_rel": 0.001,
        },
        "variants": [
            {"name": "as_printed", "stl": src, "rotate_deg": [0, 0, 0],
             "translate_before": [0, 0, 0]}
        ],
        "faces": out_faces,
        "edges": out_edges,
        "features": draft_features(faces, edges, names),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
    print(
        f"{path.name}: {len(out_faces)} faces "
        f"({sum(f['kind'] == 'plane' for f in out_faces)} planes, "
        f"{sum(f['kind'] == 'cylinder' for f in out_faces)} cylinders), "
        f"{len(out_edges)} edges, {len(doc['features'])} features, "
        f"coverage {covered / total:.1%} -> {args.out}"
    )
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey")
    s.add_argument("input_dir")
    s.add_argument("--output")
    s.set_defaults(func=cmd_survey)
    d = sub.add_parser("diagnose")
    d.add_argument("stl", nargs="+")
    d.add_argument("--min-area", type=float, default=1.0)
    d.add_argument("--output")
    d.set_defaults(func=cmd_diagnose)
    g = sub.add_parser("draft")
    g.add_argument("stl")
    g.add_argument("--out", required=True)
    g.add_argument("--min-area", type=float, default=None)
    g.set_defaults(func=cmd_draft)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
