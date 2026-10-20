# T-015: Treatment numbering still depends on world orientation for parts with twin side faces

Status: open
Opened: 2026-10-20 by the orchestrator, from the T-005 review (maintainer ruling 2026-10-20).
Depends on: T-005
Route: codex lane or Claude lane-dev (Opus, design inside). Runs one at a time with T-006 and T-008 (same file).

## What happens today

T-005 (branch `worktree-agent-aab0178974c87af52`, commit ef3b4a2) makes treatment numbering part-intrinsic. In `stl2scad/core/segmentation/defeature.py`, `_side_frame` (about lines 41-66) takes the sign of the side basis `u` from (chosen side face point - area-weighted mesh centroid) . u.

T-005 keeps one exception. When the chosen side face has a "twin" (another side plane with an anti-parallel normal and area within 0.1 % of the chosen face), it keeps the old world-axis sign `u[np.argmax(abs(u))] < 0`. Reason: the existing `chamfered_block` (two equal 2 mm chamfers) is exactly mirror-symmetric, and the pure centroid rule flipped an existing assertion (`test_chamfers_and_rounds_are_removed[chamfered_block-axis_aligned]`, F7 vs F6).

The twin test compares only the areas of the two opposite walls. A part that is NOT mirror-symmetric also reaches it: a block with a hole or pocket near one end, a boss or rib on one cap, or unequal chamfers at the two ends of the same wall pair. For those parts the numbering still depends on world orientation. `cross(axis, u)` flips with `u`, so the order along the length can swap after a 180 degree rotation. The twin case has no test.

## Rulings (2026-10-20)

- Merge the T-005 fallback now; fix the twin case in this ticket. Reason: T-005 is correct for every part without a twin, and the existing assertion must not flip. Rejected: holding T-005.
- Break the tie with an orientation-independent measure (for example treatment sizes, then the offset of the treatments or of the other features from the mesh centroid), or with a true mirror-symmetry check instead of the area check. Reason: both depend only on the part. Rejected: the area check alone.
- The world-axis sign stays only for a part that is fully mirror-symmetric, where the labels are geometrically interchangeable. Existing assertions stay unchanged.

## Settled design

`defeature.py`, `_side_frame`: replace the twin-by-area test with the orientation-independent tie-break or a true mirror-symmetry test, per the rulings. Which of the two is a lane decision inside the rulings; record the choice in the commit message. A fully mirror-symmetric part (such as `chamfered_block`) keeps the world-axis sign.

## Owns

- `stl2scad/core/segmentation/defeature.py`
- `tests/data/segmentation/treatments_expected.json`
- `tests/test_segmentation_treatments_truth.py`

## Out of scope

Any other detector change, new primitive kinds, changes to T-005's centroid rule for parts without a twin, and weakening any existing treatment assertion.

## Acceptance

- [ ] New test `test_twin_wall_numbering_is_rotation_invariant`: a twin-wall part with one asymmetric feature (equal 2 mm chamfers on both long top edges plus a through hole near one end), at rotations [0,0,0], [0,0,180] and [0,0,90]; asserts the same physical edge has the same `chamfer_N` id in all three.
- [ ] Existing tests in `tests/test_segmentation_*.py` stay unchanged, including `test_chamfers_and_rounds_are_removed[chamfered_block-axis_aligned]`.
- [ ] Ticket Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [ ] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
