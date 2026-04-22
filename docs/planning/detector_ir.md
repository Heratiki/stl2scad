# Detector Intermediate Representation (IR)

## Purpose

Before an STL becomes OpenSCAD, it becomes an IR: a typed tree of features, transforms, and boolean intent. The detector's job is to populate that IR; the emitter's job is to print it as editable SCAD. This document defines the target IR vocabulary, maps today's detector node types onto it, and marks the gaps.

This is a forward contract, not a current snapshot. Today's [stl2scad/core/feature_graph.py](../../stl2scad/core/feature_graph.py) emits a flat list of feature dicts keyed by string `type`; the IR below is the shape those should grow into as detectors come online.

## Why an IR, not direct SCAD emission

Three concrete problems the flat feature list is already bumping into:

1. **Polarity ambiguity.** A cylinder detector that runs on raw surface patches fires on both solid pins and through-holes — same surface geometry, opposite boolean sign. Without an explicit `BooleanUnion` vs `BooleanDifference` parent, the detector cannot answer "is this cylinder *added* or *subtracted*?" The IR encodes polarity in structure, so a cylinder fit becomes a child of either `union` (positive primitive) or `difference` (negative feature).
2. **Transform recovery.** Today's emitter hardcodes `translate([cx, cy, 0])` around each hole. That works for axis-aligned parts and falls over the moment rotated features ship. A `Transform` IR node (translate / rotate / mirror) between a feature and its parent separates "where is it" from "what is it" and lets the emitter factor out repeated placements into loops or mirrored modules.
3. **Ranked interpretations.** Schema-v2 fixtures already declare alternative interpretations (e.g. box-as-hollow-shell vs box-with-lid); the detector emits one flat list. An IR with a top-level `Interpretation` wrapper lets the detector carry N candidates and lets the fixture harness compare rankings directly (Beyond-dimensional-parity #1 in [feature_level_reconstruction.md](feature_level_reconstruction.md)).

The user's cylinder-in-hole observation is exactly problem #1. It is the first concrete signal that the flat list has hit its ceiling, and is the reason promoting boolean and transform nodes to first-class IR elements is higher-leverage than expanding the primitive set.

## IR Node Taxonomy

Organized by tier. Tier numbers match [feature_level_reconstruction.md](feature_level_reconstruction.md) priority ordering, not implementation difficulty.

### Root

| IR Node | Purpose |
| --- | --- |
| `Interpretation` | Top-level wrapper carrying `confidence`, `rank`, and a root feature tree. A detector run produces a list of these. |
| `FallbackMesh` | Terminal node wrapping a raw polyhedron when no parametric interpretation cleared the confidence threshold. |

### Combine (boolean intent)

| IR Node | SCAD target | Notes |
| --- | --- | --- |
| `BooleanUnion` | `union() { ... }` | Implicit at the root of most positive-feature trees. |
| `BooleanDifference` | `difference() { base; cuts... }` | Parent of every hole, slot, pocket, counterbore. |
| `BooleanIntersection` | `intersection() { ... }` | Rare; needed for envelope-clipped parts. |

Every primitive node below must appear as a child of exactly one Combine node, even if that Combine is a trivial single-child `union`. This is the structural fix for the cylinder-polarity problem.

### Transform

| IR Node | SCAD target |
| --- | --- |
| `TransformTranslate` | `translate([x,y,z])` |
| `TransformRotate` | `rotate([rx,ry,rz])` |
| `TransformMirror` | `mirror([mx,my,mz])` |
| `TransformScale` | `scale([sx,sy,sz])` |
| `TransformMatrix` | `multmatrix(M)` — fallback only |

Transforms wrap a single child feature. Patterns below are the structured alternative to repeating transforms by hand.

### Patterns

| IR Node | SCAD target | Status |
| --- | --- | --- |
| `PatternLinear` | parameterized `for (i=[0:count-1])` loop | Detector emits `linear_hole_pattern`; emitter already loops. |
| `PatternGrid` | nested row/col loop | Detector emits `grid_hole_pattern` with full metadata; emitter still lists centers (Track D). |
| `PatternRadial` | angular `for` loop around an axis | Not detected. |
| `PatternMirror` | `mirror()` + original | Not detected; highest-value missing pattern for bilaterally symmetric brackets. |

### Tier 1 — Analytic solids (positive primitives)

| IR Node | SCAD | Detector status |
| --- | --- | --- |
| `PrimitiveBox` | `cube([x,y,z])` | Detected as `box_like_solid`; **no preview emission yet** — plates only. |
| `PrimitivePlate` | `cube()` (thin axis) | Detected as `plate_like_solid`; preview emission works, incl. chamfered edges. Filleted edges pending (Track B). |
| `PrimitiveCylinder` | `cylinder(h, r)` | Not detected as a positive primitive. Polarity problem: current WIP cylinder detector fires on hole surfaces too. |
| `PrimitiveCone` / `PrimitiveFrustum` | `cylinder(h, r1, r2)` | Not detected. |
| `PrimitiveSphere` | `sphere(r)` | Not detected. |
| `PrimitiveEllipsoid` | `scale(sphere())` | Not detected. |

### Tier 1 — Cutouts (negative features, always under `BooleanDifference`)

| IR Node | SCAD emission strategy | Detector status |
| --- | --- | --- |
| `HoleThrough` | `cylinder(h=plate_t+eps, d)` | Detected as `hole_like_cutout`; emitted. |
| `HoleBlind` | depth-limited cylinder | Not detected. |
| `HoleCounterbore` | named module, shaft + bore | Generator+fixture only; **not yet detected** from raw mesh. |
| `HoleCountersink` | shaft + cone | Not detected. |
| `Slot` / `Obround` | `hull()` of two cylinders | Detected as `slot_like_cutout`; emitted. |
| `Pocket` | extruded profile, subtracted | Not detected. |
| `Notch` | face-local material removal | Not detected. |

### Tier 2 — Sketches & extrusion

| IR Node | SCAD | Detector status |
| --- | --- | --- |
| `Sketch2D` (`square`, `circle`, `polygon`, `slot2d`) | native 2D ops | Not recovered from mesh. |
| `ExtrudeLinear` | `linear_extrude(h, scale?, twist?)` | Not recovered. |
| `ExtrudeRevolve` | `rotate_extrude()` | Not recovered. |

Recovering extrusion-from-profile is the single largest future wins bucket (most mechanical parts are "profile + extrude" in intent). Blocked on 2D sketch extraction from mesh cross-sections.

### Tier 2 — Edge treatments

| IR Node | SCAD | Detector status |
| --- | --- | --- |
| `ChamferEdge` | `hull()` or boolean approximation | Detected **implicitly** (tolerant plate-edge logic), **not** as a first-class feature node. |
| `FilletEdge` / `RoundEdge` | `minkowski()` or custom module | Detection pending (Track B). |
| `DraftFace` | scaled extrusion | Not detected. |

Today chamfered edges are a *tolerance* in the plate detector, not an IR node. Promoting them to `ChamferEdge`/`FilletEdge` children of a plate or box lets the emitter print editable chamfer/fillet parameters rather than silently approximating them.

### Tier 2 — Structural features

| IR Node | Status |
| --- | --- |
| `Boss` (added cylinder/rib on a face) | Not detected. |
| `Rib` / `Web` | Not detected. |
| `Shell` / `Thickness` | Not detected. Relevant for `box_hollow_ambiguous` fixture. |
| `Tab` / `Flange` | Not detected. |

### Tier 3 — Outline / morphology

| IR Node | SCAD | Status |
| --- | --- | --- |
| `Offset2D` | `offset(r)` | Not detected. |
| `Hull` | `hull()` | Used only by slot emitter internally. |
| `Minkowski` | `minkowski()` | Not used. |
| `Projection` | `projection()` | Not used. |
| `Text` | `text()` | Not detected. |

### Tier 3 — Construction-strategy classifiers

Higher-level dispatch run *before* primitive fitting:

- `StrategyPrimitiveAssembly`
- `StrategyExtrudedSketch`
- `StrategyRevolved`
- `StrategyPlateWithHoles` *(today's main strength)*
- `StrategyBoxWithRounds`
- `StrategyTubeFitting`
- `StrategyBracket`
- `StrategyEnclosureHalf`
- `StrategyOrganic`
- `StrategyUnknown` → `FallbackMesh`

These are not SCAD emitters; they route an STL to the right specialized detector.

## Current → IR mapping (concrete)

Flat node types in [feature_graph.py](../../stl2scad/core/feature_graph.py) today, and the IR form each should grow into:

| Today's `type` string | Future IR location |
| --- | --- |
| `axis_boundary_plane_pair` | Internal detector signal, not an IR node. Drop from IR output. |
| `plate_like_solid` | `BooleanDifference { base: PrimitivePlate, cuts: [...] }` |
| `box_like_solid` | `BooleanDifference { base: PrimitiveBox, cuts: [...] }` |
| `hole_like_cutout` | `HoleThrough` (child of the enclosing `BooleanDifference`) |
| `slot_like_cutout` | `Slot` (child of the enclosing `BooleanDifference`) |
| `counterbore_hole` | `HoleCounterbore` (child of the enclosing `BooleanDifference`) |
| `linear_hole_pattern` | `PatternLinear { child: HoleThrough }` |
| `grid_hole_pattern` | `PatternGrid { child: HoleThrough }` |

## Gap summary (where to invest, in priority order)

1. **Boolean + Transform wrapping of today's flat list.** Zero new detectors, pure refactor; resolves the cylinder-polarity problem structurally and unblocks anything rotated.
2. **Chamfer/Fillet promotion to first-class IR nodes.** Currently hidden inside tolerance logic; promoting them makes Track B's filleted-edge work emit editable SCAD instead of silent approximations.
3. **Positive `PrimitiveBox` emission.** Detector already fires; emitter skips. Track B item.
4. **`PatternGrid` loop emission.** Metadata exists; emitter flat-lists. Track D.
5. **`Interpretation` wrapper for ranked candidates.** Closes the detector-native ranking gap.
6. **`PrimitiveCylinder` as a positive primitive** — but only after #1 lands. A cylinder detector without boolean context will keep mis-firing on holes.
7. **`HoleCounterbore` / `HoleCountersink` detection from mesh.** Fixture-generator side exists; detector side doesn't.
8. **`PatternMirror` and `PatternRadial`.** Next-highest-value pattern families.
9. **Shell / `Boss` / `Rib` / `Tab`.** Structural features.
10. **Sketch2D recovery and `ExtrudeLinear` / `ExtrudeRevolve` from cross-sections.** Largest Tier-2 payoff, also largest implementation scope.

Items below this line are deferred until the Real-World Feedback Loop (Phases 1–3 of [feature_level_reconstruction.md](feature_level_reconstruction.md)) raises real-world pass-rate meaningfully:

- Threads, knurls, drafted faces, lofts
- `Offset2D`, `Minkowski`, `Projection`, `Text`
- Organic / freeform fallbacks beyond `FallbackMesh`

## Schema versioning

When the flat list migrates to this IR, bump `schema_version` in the fixture manifest and in feature-graph JSON output. Breakages from the flat representation are expected and should land in one coordinated change: IR types, emitter, fixture harness, and all checked-in `.scad` regenerations together.

## Non-goals

- This document does **not** replace [feature_level_reconstruction.md](feature_level_reconstruction.md); that roadmap still drives execution order. This document is the target vocabulary the roadmap is executing toward.
- This document does **not** authorize new detector work. Track A → B → C → D on the roadmap remains the critical path. Use this IR as the *shape* that new detectors must fit into, not as a to-do list to start pulling from.
