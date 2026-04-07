# CGAL Integration Boundary (Phase 2)

## Decision
Use an **external helper executable** as the initial CGAL integration boundary, with JSON over stdin/stdout.

## Why This Boundary
1. Keeps Python package installation lightweight for default users.
2. Avoids binding/distribution complexity in early Phase 2.
3. Allows independent iteration on CGAL-side implementation language/toolchain.

## Runtime Discovery
`stl2scad` resolves helper path in this order:
1. Explicit path (future CLI/config extension)
2. `STL2SCAD_CGAL_HELPER` environment variable
3. PATH search for:
   - `stl2scad-cgal-helper`
   - `stl2scad-cgal-helper.exe`
   - `stl2scad-cgal-helper.py`

## Request Protocol
Primitive detection command invocation:

```text
<helper> detect-primitive --format json
```

stdin JSON payload:

```json
{
  "operation": "detect_primitive",
  "tolerance": 0.01,
  "mesh": {
    "triangles": [[[x, y, z], [x, y, z], [x, y, z]], ...]
  }
}
```

Capability command invocation:

```text
<helper> capabilities --format json
```

stdout JSON payload:

```json
{
  "schema_version": 1,
  "helper_mode": "prototype",
  "cgal_bindings_available": false,
  "cgal_modules": [],
  "operations": ["detect_primitive"],
  "supported_primitives": ["box", "sphere", "cylinder", "cone", "composite_union"],
  "engines": ["geometric_region_fallback"]
}
```

## Response Protocol
stdout JSON payload:

```json
{
  "detected": true,
  "scad": "translate([..]) cylinder(...);",
  "primitive_type": "cylinder",
  "confidence": 0.91,
  "diagnostics": {
    "method": "shape_detection"
  }
}
```

If no reliable primitive is found:

```json
{
  "detected": false,
  "primitive_type": null,
  "confidence": 0.22,
  "diagnostics": {
    "reason": "low_confidence"
  }
}
```

## Current Behavior in `stl2scad`
1. `--recognition-backend cgal` attempts direct CGAL Python binding detection first when `CGAL.CGAL_Shape_detection` is importable.
2. Direct Python binding detection currently accepts high-coverage sphere output only; partial/unsupported shapes decline.
3. If direct Python bindings decline or are unavailable, the backend attempts CGAL helper detection.
4. If CGAL helper declines or fails, current implementation falls back to `trimesh_manifold` backend when available.
5. If neither yields a confident primitive, converter falls back to polyhedron output.

## Phase 2 Status
1. Minimal helper prototype implemented (`scripts/stl2scad-cgal-helper.py`).
2. End-to-end adapter/protocol tests added (`tests/test_cgal_backend.py`).
3. Diagnostics now propagate into conversion metadata and verification JSON reports.
4. Helper capability reporting now makes CGAL binding availability explicit.

## Remaining Work (Post-Phase 2)
1. Replace prototype helper internals with true CGAL shape-detection implementation.
2. Add CI job/profile that runs against a packaged helper binary/toolchain.
3. Expand boolean/topology-aware reconstruction for complex multi-primitive models.
