# Phase 2 Release Checklist (CGAL Backend)

## Scope
Close out the Phase 2 deliverable for optional CGAL-backed parametric recognition.

## Checklist
- [x] Integration boundary documented (`docs/planning/cgal_integration_boundary.md`)
- [x] Adapter implemented (`stl2scad/core/cgal_backend.py`)
- [x] `cgal` recognition backend wired through converter/recognition routing
- [x] Helper prototype available for end-to-end protocol validation (`scripts/stl2scad-cgal-helper.py`)
- [x] Converter metadata includes backend/primitive fields for CGAL path
- [x] Verification JSON report includes conversion metadata from SCAD header (including backend diagnostics)
- [x] Automated tests cover:
  - [x] helper path resolution
  - [x] JSON protocol parse/error handling
  - [x] `cgal` -> `trimesh_manifold` fallback behavior
  - [x] helper end-to-end detection on benchmark fixture
  - [x] converter metadata emission for `cgal`
  - [x] verification-report metadata propagation
- [x] User-facing docs updated:
  - [x] README backend/install/CLI coverage for `cgal`
  - [x] tests README includes Phase 2 test target

## Validation Commands
```bash
pytest tests/test_cgal_backend.py -q
pytest tests/test_cli.py -q
pytest tests/test_conversion.py -q -k "phase1_"
```

## Notes
- CGAL remains optional and does not impact default installation path.
- Current helper is a protocol-compatible prototype; real CGAL engine logic can replace it without changing Python-side contract.
