# Parametric Conversion Roadmap (Trimesh+Manifold -> CGAL)

## Purpose
Define an implementation plan for expanding parametric STL-to-SCAD conversion without losing existing project priorities (fallback safety, CLI stability, verification quality, GUI parity, and maintainability).

## Current Baseline (2026-04-06)
1. Parametric recognition supports axis-aligned box/cube only.
2. `--parametric` is opt-in and safely falls back to polyhedron output.
3. Verification metrics include volume, area, bbox, Hausdorff (sampled), and normal deviation (sampled).
4. CLI contract is stable (`convert`, `verify`, `batch`; exit codes `0/1/2`).

## Architecture Principles
1. Keep parametric recognition additive and behind `--parametric`.
2. Never remove polyhedron fallback path.
3. Gate every recognition expansion with regression tests and verification thresholds.
4. Keep deterministic behavior where possible (or explicitly seedable).
5. Keep backend-specific code isolated behind a small adapter interface.

## Planned Phases

## Phase 0: Foundations (short, before feature expansion)
### Goals
1. Prepare code structure for multiple recognition backends.
2. Add deterministic controls and benchmark fixtures for verification.

### Work
1. Introduce a recognition backend interface (default `native`, then `trimesh_manifold`, then optional `cgal`).
2. Add seeded sampling mode for verification metrics.
3. Add benchmark fixture set:
   - boxes (already supported)
   - cylinders (axis-aligned and rotated)
   - spheres
   - cones/frustums
   - multi-part solids (union and subtraction-like geometry)
4. Add perf baseline script for representative mesh sizes.

### Exit Criteria
1. Existing tests pass unchanged.
2. New fixture scaffolding and seeded mode are available and documented.

## Phase 1: Trimesh + Manifold Backend (primary near-term deliverable)
### Goals
1. Increase practical primitive recognition coverage quickly in Python.
2. Improve mesh robustness before fitting/recognition.

### Work
1. Add optional dependencies and backend checks for `trimesh` and `manifold3d`.
2. Add preprocessing pipeline:
   - watertight/manifold checks
   - repair normalization (remove degenerates, merge close vertices, orient/fix normals where needed)
   - connected-component segmentation
3. Add primitive candidates:
   - cylinder (axis + radius + height fit)
   - sphere (center + radius fit)
   - cone/frustum (axis + radii + height fit)
4. Add confidence scoring and reject thresholds; on low confidence, fallback to polyhedron.
5. Add composite model assembly for multi-component cases:
   - emit independent primitives with transforms where possible
   - preserve deterministic ordering for output stability
6. Keep output conservative:
   - prefer exact primitive SCAD when confidence is high
   - otherwise fallback

### Exit Criteria
1. Recognition pass rate improves on fixture set with no regression in fallback safety.
2. Verification tolerances hold for accepted parametric outputs.
3. CLI and GUI behavior remain backward compatible.

## Phase 2: CGAL Backend (higher precision/coverage path)
### Goals
1. Add stronger primitive/shape detection for hard meshes.
2. Provide an optional advanced backend for users who install CGAL toolchain.

### Work
1. Define CGAL integration boundary (Python extension, helper executable, or service wrapper).
   - Current choice: helper executable JSON protocol (see `docs/planning/cgal_integration_boundary.md`).
2. Use CGAL shape detection for primitive extraction where Phase 1 confidence is low.
3. Add topology/boolean-aware post-processing for multi-primitive reconstruction.
4. Add backend selection strategy:
   - `native` -> `trimesh_manifold` -> `cgal` fallback order (configurable)
5. Add backend-specific diagnostics to reports (chosen backend, confidence, reason for fallback).

### Exit Criteria
1. Difficult fixtures show measurable recognition gains versus Phase 1 only.
2. Optional CGAL path does not affect default install reliability.
3. Packaging and documentation for optional backend are complete.

## Do-Not-Forget Checklist (project-wide)
1. Fallback safety: every failed/low-confidence recognition must still emit valid polyhedron SCAD.
2. CLI contract stability: keep commands/flags/exit codes stable unless versioned migration is planned.
3. GUI parity: expose new backend/parametric controls in GUI without losing existing workflows.
4. Verification determinism: seeded sampling mode for reproducible CI and local comparisons.
5. Performance budgets: track conversion time and memory on small/medium/large fixtures.
6. Documentation: README + CLI help + developer notes for backend installation and behavior.
7. Test strategy:
   - unit tests for fitters and confidence logic
   - integration tests for convert/verify/batch with `--parametric`
   - regression tests for known problematic meshes
8. Dependency and licensing review:
   - document optional dependency footprints
   - confirm distribution strategy for each backend before enabling by default

## Implementation Tracking
Use this checklist as an execution board:

- [x] Phase 0 complete
- [x] Phase 1 backend skeleton merged
- [x] Phase 1 primitive detection merged
- [x] Phase 1 confidence/fallback tuning complete
- [x] Phase 1 docs/tests/perf gates complete
- [x] Phase 2 integration design approved
- [x] Phase 2 prototype merged behind feature flag
- [x] Phase 2 docs/tests/release checklist complete

## Suggested Milestone Gates
1. Milestone A: Foundations + deterministic verification.
2. Milestone B: Trimesh+Manifold primitive expansion in production behind `--parametric`.
3. Milestone C: Optional CGAL advanced backend validated on hard fixtures.
