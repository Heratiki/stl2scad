# Real parts: next target for the segmentation pipeline

Status: draft, 2026-10-20. Follows "Next target" in
[segmentation_composite_bracket.md](segmentation_composite_bracket.md).

## Blocker: the Hero Me corpus is not on this machine

The 20 parts in [artifacts/local_corpus_report.html](../../artifacts/local_corpus_report.html)
were scored on 2026-04-28 on another machine (Windows paths). The manifest
(`.local/local_corpus.json`, gitignored) and the STL files are not on this Linux machine.
A search of the full disk found no `HMG*` or "Hero Me" files. The parts are also
license-restricted on Thangs (MediaMan3D), so they were not downloaded.

So triangle counts and bounding boxes for the 20 parts could not be measured. The table
below uses only the report: the file name, the bucket, and the thumbnail embedded in the
report.

| # | Part (path under the corpus root) | Bucket | Shape (from thumbnail) | Simplicity |
|---|---|---|---|---|
| 1 | Hero Me Gen7 Release V3.2/ABL Mounts/HMG7 BL-CR Touch Medium Left Wing V2.stl | polyhedron | two offset blocks, slots | medium |
| 2 | .../DyzeXrtruder/HMG7.3 DyzeXtruder Pro Front Mount.stl | polyhedron | U bracket, round end, holes | medium |
| 3 | .../Sailfin/HMG7.3 Sailfin A Rear Mount.stl | polyhedron | flat plate, countersunk holes | **simple** |
| 4 | .../Sailfin/HMG7.3 Sailfin Front-Rear Sherpa Mount.stl | polyhedron | plate, round ends, holes | simple |
| 5 | .../Sovol SV01/HMG7.2 Sovol SV01 BMG Mirrored Mount.stl | polyhedron | L bracket, gusset, motor hole | medium |
| 6 | Gantry Adapters/Creality/HMG7 Ender 3 V2 Neo Gantry Clip.stl | polyhedron | block plus a large cylinder boss with a bore | **simple** |
| 7 | .../HMG7.3 Box X Carriage Bottom.stl | polyhedron | plate, chamfered top edges | simple |
| 8 | .../HMG7.3 MGN9-H Linear Rail Front X Carriage V2.stl | polyhedron | thin plate, many holes | medium |
| 9 | .../PrinterMods/HMG7 PrinterMods V1.3  Ender 5 Gantry Clip.stl | polyhedron | block with a raised rib, round ends | **simple** |
| 10 | .../PrinterMods/HMG7 XChange High Mount Gantry Adapter.stl | polyhedron | open frame, bosses | complex |
| 11 | .../Sovol/HMG7.3 Sovol SV06-Plus Gantry Adapter.stl | polyhedron | plate, bosses, holes | medium |
| 12 | .../Sunlu/HMG7.3 Sunlu S8 Gantry Clip V3.stl | polyhedron | thin bar, round ends | medium |
| 13 | .../HMG7.3 Wham Bam Universal Linear Rail High Center Gantry Adapter.stl | polyhedron | open frame | complex |
| 14 | .../HMG7.3 Phaetus DropEffect XG5 Mount.stl | polyhedron | plate, large bosses | complex |
| 15 | .../HMG6-tall-single-5015.stl | polyhedron | duct, free-form | complex |
| 16 | .../HMG6-tall-lightweight-forward-5020-left.stl | polyhedron | duct, free-form | complex |
| 17 | Hotend_Chain_Mount_v14_-_With_Ender_Logo.stl | axis pairs | block, logo, many features | complex |
| 18 | Mounted Clip.stl | parametric preview | thin bent clip | medium |
| 19 | Sensor_Cap_Cable_Chain_link.stl | axis pairs | chain link, tori | complex |
| 20 | Utility Knife/sheath1.stl | polyhedron | free-form sheath | complex |

Recommended Hero Me targets when the corpus is back: **#3 Sailfin A Rear Mount** (plate +
countersunk holes), **#6 Ender 3 V2 Neo Gantry Clip** (block + cylinder boss + bore),
**#9 PrinterMods Ender 5 Gantry Clip** (block + rib + round ends). These are prismatic
mounts with holes, bosses and rounds.

To finish the Hero Me target, on a machine that has the corpus:

```bash
python scripts/survey_real_parts.py survey "<corpus root>" --output artifacts/real_parts_survey.json
python scripts/survey_real_parts.py draft "<path>/HMG7.3 Sailfin A Rear Mount.stl" \
    --out tests/data/segmentation/real/hmg_sailfin_rear_expected.json
python scripts/survey_real_parts.py diagnose "<path>/HMG7.3 Sailfin A Rear Mount.stl"
```

## Stand-in parts used now

To make progress, three real third-party parts that are on this machine were used. They
are from the "MEMO BOY" sticky-note holder in `~/Downloads/MEMO_BOY___CONSOLE_STICKY_NOTE_HOLDER/`.
They are not copied into the repo. The `source_stl` field holds the absolute path.

The other local STLs were rejected: the dragon cup (free-form, 50 MB), the book holder
(286 faces, open frame), the drawer (an R200 curved face), the top shell and the A/B pad
(over 100k triangles, free-form).

| Short name | File | Triangles | Bbox (mm) | Why |
|---|---|---|---|---|
| `memo_stencil6` | MEMO BOY - STENCIL - 6.STL | 1148 | 76.6 x 1.0 x 82.6 | Simplest. A 1 mm plate, 2 through slots, 7 corner rounds. All surface is planes or cylinders. |
| `memo_cartridge` | MEMO BOY - CARTRIDGE.STL | 1534 | 80.6 x 12.0 x 83.8 | Plate with 45° edge chamfers, two additive feet, a top notch with R2 concave arcs. |
| `memo_power_button` | MEMO BOY - BUTTON - POWER.STL | 3568 | 27.0 x 11.0 x 10.0 | Small lever: bar + head + rib with R0.5 half-round ends, R1 rounds. About 4 % free-form. |

## Draft ground truth

Files: `tests/data/segmentation/real/<short_name>_expected.json`. The schema is the schema
of `composite_bracket_expected.json`, plus `status`, `short_name`, `source_stl`,
`selection_note`, `hand_check`, coverage fields, and per-face `area_mm2` (and `length`,
`sweep_deg`, `fit_max_residual_mm` for cylinders). Face IDs are `P<n>` (plane) and
`C<n>` (cylinder). Coordinates are in the STL frame. There is one variant (`as_printed`).

The drafts come from `scripts/survey_real_parts.py draft`. That code does not import the
segmentation package. It welds vertices, groups flat-connected triangles into planes,
removes narrow facet strips between parallel creases, groups the rest into smooth patches,
fits the axis from the normal covariance and a circle by least squares, and classifies
edges by the signed dihedral (tangent ≤ 7.5°). Feature rules: concave cylinder + concave
cap = blind hole; two half-cylinders that share two walls = slot; cylinder strip tangent to
two planes = fillet (concave) or edge round (convex). The `body` feature in each file was
added by hand from the plane list.

Check of the method: on `composite_bracket.stl` and the rotated variant, the draft gives
13 faces (10 planes, 3 cylinders), 25 edges (21 convex, 2 tangent, 2 concave), and the
fillet R3, boss R6 h6 and blind hole R2.5 d3. This is the same as the hand-written
`composite_bracket_expected.json`.

| Part | Faces (plane / cyl) | Edges (convex / tangent / concave) | Features | Area not fitted |
|---|---|---|---|---|
| `memo_stencil6` | 16 / 11 | 50 / 22 / 3 | body, 2 through slots (w 2.0, l 66.6, d 1.0), 7 edge rounds (six R2, one R1) | 0 mm² |
| `memo_cartridge` | 116 / 10 | 145 / 87 / 6 | body (2.0 plate), 2 concave R2 arcs (notch), 6 rounds on the feet (R 2.2–16), 2 small R3 arcs | 30.3 mm² |
| `memo_power_button` | 54 / 5 | 39 / 18 / 6 | body, 2 rib ends R0.5, 3 R1 rounds | 26.6 mm² |

## Diagnostic: current `segment_mesh` on these parts

Run with `scripts/survey_real_parts.py diagnose` on 2026-10-20 (code in the working tree, not committed).
No exceptions. "Faces ≥ 1 mm²" leaves out the small facet patches.

| Part | Runtime | Faces (plane / cyl) | Faces ≥ 1 mm² (plane / cyl) | Edges convex / tangent / concave | Cylinders found |
|---|---|---|---|---|---|
| composite_bracket (control) | 0.07 s | 10 / 3 | 10 / 3 | 21 / 2 / 2 | R6 convex, R3 concave, R2.5 concave |
| `memo_stencil6` | 0.42 s | 16 / 11 | 16 / 11 | 50 / 22 / 3 | 6 × R2 convex, 1 × R1 convex, 4 × R1 concave (axis Y) |
| `memo_cartridge` | 0.43 s | 665 / 5 | 95 / 3 | 282 / 1046 / 6 | 2 × R2 concave (notch), R1.31 convex, 2 × R3 convex |
| `memo_power_button` | 0.77 s | 1814 / 5 | 18 / 5 | 143 / 3230 / 6 | 2 × R0.5 convex (rib ends), 3 × R1 convex |

Findings:

- **Stencil**: the face counts, all 11 cylinders and the edge convexity counts (50 / 22 / 3) match the draft. This is the first real
  part where steps 1–3 agree with an independent reference.
- **Cartridge**: the 2 notch arcs are found. The curved outline of the feet (six arcs in the
  draft, R 2.2–16) stays as about 570 facet planes. Those faces are not cylinders at the
  segmentation tolerances; they may be a spline.
- **Power button**: the 5 cylinders match the draft. The free-form head side gives
  about 1800 facet planes and 3230 tangent edges.
- Steps 4–5 (`detect_features`, emit) were not run here.

## What the user must check by hand

For each file, open the STL in a viewer and check against the JSON:

1. **All three**: the `body` feature text (profile and thickness), and the `hand_check` list.
2. **Stencil**: the slot positions (x = 25.3 and 51.3, z 11..77.6) and the outline of the lower tab
   (x 23.5..53.1, step at z 3, R1 at (52.1, 4)). Are there 7 corner rounds?
3. **Cartridge**: are the foot outlines true arcs or a spline? If they are a spline, mark
   C120–C125 as free-form and remove the edge-round features. Check the chamfer width. Is
   the notch a cut through the 2 mm plate?
4. **Power button**: is the unfitted head side a cylinder about Y? The draft gives the rib ends as
   `convex_arc`. Rename them to a rib feature if you agree.
5. **Faces under 1 mm²**: the drafts list every planar face of 0.25 mm² or more. Decide
   whether the target tests should ignore small faces, as the bracket test has none.
6. Decide whether the stand-ins are acceptable, or whether the target must wait for the
   Hero Me files (#3, #6, #9 above).
