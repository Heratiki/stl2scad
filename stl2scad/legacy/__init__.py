"""Archived legacy pipeline (T-003, T-004).

Nothing here runs by default, and nothing in stl2scad/ outside this package
imports it. The code is superseded by stl2scad.core.segmentation (the only live
conversion path, via stl2scad.core.conversion) and is kept for reference, for
scripts under scripts/, and for the tests under tests/legacy/
(STL2SCAD_LEGACY_TESTS=1).

Contents: the whole-mesh conversion path (converter), the feature-graph
detectors (feature_graph, feature_inventory, linear_extrude_recovery,
revolve_recovery), primitive recognition (recognition, cgal_backend,
recognition_sweep), the legacy perf baseline, and the detector-tuning and
corpus-scoring tools (tuning/, corpus/).
"""
