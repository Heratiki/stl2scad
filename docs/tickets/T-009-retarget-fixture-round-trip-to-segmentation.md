# T-009: Retarget the fixture round-trip to the segmentation pipeline

Status: landed (worktree-agent-a0d77460d4116ade0, 2026-10-20). Route: Sonnet lane-dev.
Opened: 2026-10-20 by the ticket-writer, from the maintainer's rulings and a measurement of the same date.
Depends on: T-004

## What happens today

Measurement 2026-10-20 at HEAD 39185de, segmentation pipeline over every rendered fixture: 95 fixtures (92 in the manifest plus `l_bracket_wide`, `box_side_cutout`, `revolve_vase_dome`, which are not in the manifest). Result: 61 parametric, 34 fallback, 0 errors.

| Type | parametric / fallback |
|---|---|
| plate | 30 / 10 |
| box | 13 / 5 |
| revolve | 0 / 11 |
| cylinder | 6 / 0 |
| non_revolve | 5 / 1 |
| prism | 4 / 0 |
| cone | 0 / 3 |
| l_bracket | 2 / 0 |
| sphere | 0 / 1 |
| torus | 0 / 1 |
| unlisted | 1 / 2 |

- Every parametric output has Hausdorff <= 1e-6 mm.
- Emitted Customizer groups matched the manifest counts on 60 of 60 parametric manifest fixtures (Hole N to `hole_count`, Slot N to `slot_count`, Through Hole plus Blind Hole to `counterbore_count`).
- Fallback reasons: "No matching opposite section caps for an extruded body" 13; "Unsnapped feature solid failed the Hausdorff gate" 11; "Unsupported cylinder topology at F0/F3" 5; "Editable cylinders currently require a profile-side host" 3; "Unsupported through-cut section: expected circular hole or stadium" 1; "An arc profile needs a straight side to define its frame" 1.
- A fallback is signalled by a `// Full mesh fallback: <reason>` line in the SCAD. Hausdorff is in the header's `measured Hausdorff` line.
- Runtime: median 6 s per fixture, about 52 CPU-minutes in total. Slowest: `plate_multi_pattern_mixed_edge` 691 s, `plate_3x3_grid` 596 s, `plate_4x4_grid` 424 s; the sphere and torus fallbacks about 120 s each.
- Manifest fields with no segmentation counterpart: the `*_like_solid`, `revolve_solid` and `linear_extrude_solid` flags, linear and grid pattern counts, rectangular cutout and pocket counts.
- `tests/test_feature_fixtures.py` `test_feature_fixture_round_trip_detection` asserts against the legacy detector; after T-004 those tests live in `tests/legacy/`, so the round-trip invariant has no live test.

## Rulings (2026-10-20)

- Retarget now rather than rewrite the harness. Reason: the manifest, generator and SCAD library already work.
- New invariant: each fixture either is parametric, with Hausdorff within the gate and matching hole, slot and counterbore counts, or falls back with its expected reason and is listed by name as a known gap (xfail per fixture, reason string asserted). Rejected: a blanket skip of failing fixtures.
- Runtime: fixtures over about 30 s get a pytest `slow` marker, excluded from the default full run and run on demand with `-m slow`. The marker is registered, and the default run deselects it (addopts or conftest). When the perf ticket lands the marker goes.
- Segmentation expectations go in a separate file, preferably `tests/data/segmentation/fixture_expectations.json`, so the byte-exact SCAD regeneration test is untouched. The manifest gets new fields only if needed. `.gitignore` ignores `*.json`, so the file needs one `!` rule.
- The roadmap-coverage test is unchanged.

## Settled design

- The lane chooses between extending `tests/test_feature_fixtures.py` and a new `tests/test_segmentation_fixtures.py`, and states the choice in its report. The new file is under the `test_segmentation_*` pattern, which is the segmentation test namespace.
- `fixture_expectations.json`: per fixture, `status` (`parametric` or `known_gap`), the expected counts (`hole_count`, `slot_count`, `counterbore_count`) where parametric, the expected fallback reason string where known gap, and `slow` (true over about 30 s). Seed it from the measurement above; fixtures are rendered and converted to confirm.
- Test reads the `// Full mesh fallback:` line and the `measured Hausdorff` header line, and counts Customizer groups.
- Known-gap fixtures use `pytest.xfail`/`xfail(strict=True)` with the reason string asserted, so a fixture that starts working fails loudly and must be moved to `parametric`.
- Register `slow` in `pytest.ini` markers and deselect it by default (`-m "not slow"` in addopts, or a conftest hook; the lane picks, and `-m slow` must still collect them).

## Owns

- `tests/test_feature_fixtures.py` or the new `tests/test_segmentation_fixtures.py` (lane's choice)
- `tests/data/segmentation/fixture_expectations.json`
- `.gitignore` (one `!` rule)
- `pytest.ini` and/or `tests/conftest.py` (marker registration and deselect)
- `docs/tickets/T-009-retarget-fixture-round-trip-to-segmentation.md` (Status line only)

## Out of scope

- Fixing any fallback (the 34 gaps are separate work).
- Changing the manifest, the generator or the checked-in SCAD files.
- Performance work on the slow fixtures.
- Mapping the unmapped manifest fields (`*_like_solid` flags, pattern counts, cutout and pocket counts).
- Editing CLAUDE.md (orchestrator).

## CLAUDE.md wording after T-009 (the orchestrator edits it)

- Invariant 2, "Segmentation round-trip": every fixture either converts parametric with Hausdorff within the gate and matching hole, slot and counterbore counts, or falls back with its expected reason and is listed by name as a known gap in `tests/data/segmentation/fixture_expectations.json`. Fixtures over about 30 s carry the `slow` marker (`-m slow` to run them). Never weaken a count or reason assertion to make a fixture pass; move it to the known-gap list with its reason instead.
- Invariants 1 and 3 unchanged.

## Acceptance

- [x] New or retargeted round-trip test (name chosen by the lane): for every fixture in `fixture_expectations.json`, asserts parametric plus Hausdorff within the gate plus expected counts, or the expected fallback reason.
- [x] A test asserting every rendered fixture has an entry in the expectations file and every entry names an existing fixture.
- [x] Every known-gap fixture asserts its reason string.
- [x] `pytest -m slow --collect-only` collects exactly the fixtures flagged `slow` (those over about 30 s); the default run deselects them.
- [x] Existing tests unchanged: `test_feature_fixture_manifest_matches_checked_in_scad` and `test_feature_fixture_manifest_covers_roadmap_stress_cases`.
- [x] Scoped run of the fast set passes (lane may run it with the flock prefix from `test_scoped`).
- [x] Status set to `landed (<branch>, YYYY-MM-DD)` in the lane's commit.
- [x] Gates pass: `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,.claude,build,dist` and `node scripts/check-tickets.mjs`.

Do NOT run the test harness. Stage paths explicitly.
