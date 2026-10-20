# T-013: Hollow box gives a wrong model that only the gate stops

Status: open
Opened: 2026-10-20 by the orchestrator, from a measurement of the segmentation pipeline (`emit_scad(None, mesh)`) over the 95 feature fixtures in `tests/data/feature_fixtures_scad/` (2026-10-20; 61 parametric, 34 fallback, 0 exceptions). Fallback is read from the `// Full mesh fallback: <reason>` line and the Hausdorff from the `measured Hausdorff` header line.
Depends on: none
Route: codex lane (segmentation work).

## What happens today

box_hollow_ambiguous (a hollow box shell) is built as a solid by segmentation, giving a measured Hausdorff of 5 mm; the gate then forces a polyhedron fallback ("Unsnapped feature solid failed the Hausdorff gate", 0.9 s). This is a wrong-model (false positive caught by the gate): the detector does not recognise an enclosed cavity or inner shell. `CLAUDE.md` already notes that legacy box detection can false-positive on hollow shells; this is the segmentation-side instance. No plan covers hollow bodies or inner shells.

The standing maintainer rule (2026-10-20) is to ticket every detector false positive or primitive issue; the maintainer may set `wontfix` later.

## Rulings (2026-10-20)

- IN SCOPE, as negative primitives. The maintainer overrode the wontfix suggestion. Rejected: wontfix, and rejection-only with a named reason.
- Open shells (open-top boxes) are pockets and belong to T-011, not this ticket.
- Route stays codex.

## Settled design

Split the mesh into connected shells. A shell with negative signed volume (inward normals) is a void: flip it and run it through the same segmentation pipeline as a solid, then emit `difference() { outer(); void(); }`. The Hausdorff gate applies to the whole result. This generalises to any void segmentation can model (box, cylinder, later revolve). A void that cannot be modelled makes the part fall back as today.

## Owns

`stl2scad/core/segmentation/` (the module the maintainer picks after the design is confirmed) and a new `tests/test_segmentation_<topic>.py`

## Out of scope

- Through-holes and pockets, including open shells such as open-top boxes (T-011).
- Legacy `feature_graph.py` box detection (T-004).

## Acceptance

- [ ] New test `test_hollow_box_emits_negative_box`: box_hollow_ambiguous (24x16x12 with an enclosed 14x6x2 cavity) converts parametric within the gate, with the cavity as a labelled negative box inside `difference()`.
- [ ] New test `test_unmodelable_void_falls_back`: a void that cannot be modelled falls back to polyhedron as today.
- [ ] New test `test_solid_box_unchanged`: box_cubic stays parametric.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
