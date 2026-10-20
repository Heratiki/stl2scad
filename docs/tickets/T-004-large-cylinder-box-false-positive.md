# T-004: Large-diameter cylinder is detected as a box with the revolve detector off

Status: open (needs a maintainer ruling on option A or B before any lane starts)
Opened: 2026-10-20 by the ticket-writer, from the T-003 lane report, confirmed by lane-verifier. Filed under the maintainer's standing rule to ticket every false positive.
Depends on: T-003 (merged 730d6b4)

## What happens today

- `DetectorConfig.enable_revolve_detection` is False since T-003. Before T-003 a revolve result suppressed the later checks through the `if not revolve_features` guards in `stl2scad/core/feature_graph.py` (about lines 462-545). With revolve off, `revolve_features` is empty and those checks run.
- At lines 453 and 479-481, `_extract_axis_aligned_box_features` (defined at line 2501) is called first. If it returns a `box_like_solid`, `box_found` is true and `_extract_cylinder_like_solid` is skipped.
- Fixture `cylinder_large_diameter` (`tests/data/feature_fixtures_manifest.json` line 3422; d=50, h=20, axis z; SCAD in `tests/data/feature_fixtures_scad/cylinder_large_diameter.scad`) expects `box_like_solid: false`. The legacy graph returns `box_like_solid` count 1 (expected 0). This was measured by the T-003 lane and confirmed by lane-verifier. This ticket's writer did not re-run it.
- The box branch (lines 2641-2645) accepts on `paired_axes == box_paired_axes_required and confidence >= box_confidence_min`, or on `_tolerant_box_confidence(...) >= box_tolerant_confidence_min`. Neither test limits the area of curved (non-axis-normal) faces. Hypothesis, not verified: the cylinder side facets that are tangent to the bbox at the x and y extremes pass the boundary masks (normal and center-near-extreme tests), so all three axes look paired.
- The fixture is xfailed by name in `_REVOLVE_ARCHIVED_NON_REVOLVE_FIXTURES` (`tests/test_feature_fixtures.py` lines 39-51), with the comment "With revolve off nothing suppresses the box check: got a box_like_solid."
- CLAUDE.md "Failure analysis" already notes that box detection can false-positive.
- Segmentation pipeline (`--pipeline segmentation`, `stl2scad/core/segmentation/`): not checked. No test under `tests/test_segmentation_*.py` and no doc under `docs/planning/segmentation_*.md` mentions this fixture, and `tests/data/segmentation/` holds only the composite bracket and rounded plate. Nobody has run it on this fixture.

## Rulings (2026-10-20)

- None yet. The maintainer must choose A or B below before a lane starts.
- Option A: fix the box detector so a mesh with large curved (non-axis-normal) area is not a box, then remove `cylinder_large_diameter` from the xfail set. Cost: a threshold change inside a pipeline that is being replaced; risk to the other box and plate fixtures (chamfer and fillet tolerant cases).
- Option B: wontfix, because the legacy pipeline is being replaced by the segmentation pipeline. Cost: the fixture stays xfailed and the legacy default keeps a known false positive.

## Settled design

Nothing is settled. Under option A only: the lane changes the box branch of `_extract_axis_aligned_box_features` to reject a mesh whose curved-area share is above a threshold. The threshold value is a design question for the maintainer ("Confirm before implementing"). Tolerant chamfer or fillet boxes must still pass.

## Owns

Under option A:

- `stl2scad/core/feature_graph.py` (box detection only)
- `tests/test_feature_fixtures.py` (remove the name from `_REVOLVE_ARCHIVED_NON_REVOLVE_FIXTURES`)

Under option B: nothing; set Status to `wontfix` with the reason.

## Out of scope

- Any other fixture in the xfail set (`cylinder_plain`, `cylinder_short_disk`, `cylinder_x_axis`, `cylinder_y_axis`, `cylinder_narrow_tall`, `prism_octagon`).
- Changes to the revolve detector, `enable_revolve_detection`, plate, cylinder or linear-extrude detection.
- Changes to the segmentation pipeline.
- Weakening any stress-case or dimensional assertion.

## Acceptance

Under option A:

- [ ] `test_feature_fixture_round_trip_detection` (existing): `cylinder_large_diameter` round-trips with the flag off and `_is_revolve_archived_fixture` no longer covers it. This fixture reports no `box_like_solid`.
- [ ] No other fixture changes outcome. Existing tests in `tests/test_feature_fixtures.py` stay unchanged apart from the one name removed from the xfail set.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Under option B:

- [ ] Ticket Status set to `wontfix` with the reason; no code changes.

Do NOT run the test harness. Stage paths explicitly.
