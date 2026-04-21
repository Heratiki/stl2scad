import sys

def modify(content):
    # 1. Imports and signature of build_feature_graph_for_stl
    old_sig = """def build_feature_graph_for_stl(
    stl_file: Union[Path, str],
    root_dir: Optional[Union[Path, str]] = None,
    normal_axis_threshold: float = 0.96,
    boundary_tolerance_ratio: float = 0.01,
) -> dict[str, Any]:
    \"\"\"
    Build a conservative feature graph for one STL file.
    \"\"\"
    path = Path(stl_file)"""
    new_sig = """from stl2scad.tuning.config import DetectorConfig

def build_feature_graph_for_stl(
    stl_file: Union[Path, str],
    root_dir: Optional[Union[Path, str]] = None,
    normal_axis_threshold: Optional[float] = None,
    boundary_tolerance_ratio: Optional[float] = None,
    config: Optional[DetectorConfig] = None,
) -> dict[str, Any]:
    \"\"\"
    Build a conservative feature graph for one STL file.

    config overrides defaults; the legacy kwargs override config fields when
    provided, preserving every existing call site.
    \"\"\"
    resolved = config or DetectorConfig()
    if normal_axis_threshold is not None or boundary_tolerance_ratio is not None:
        import dataclasses
        overrides: dict[str, float] = {}
        if normal_axis_threshold is not None:
            overrides["normal_axis_threshold"] = normal_axis_threshold
        if boundary_tolerance_ratio is not None:
            overrides["boundary_tolerance_ratio"] = boundary_tolerance_ratio
        resolved = dataclasses.replace(resolved, **overrides)
    path = Path(stl_file)"""
    content = content.replace(old_sig, new_sig)

    # 2. update calls in build_feature_graph_for_stl
    content = content.replace("normal_axis_threshold=normal_axis_threshold,\n        boundary_tolerance_ratio=boundary_tolerance_ratio,", "config=resolved,")
    content = content.replace("normal_axis_threshold=normal_axis_threshold,", "config=resolved,")
    content = content.replace("_extract_repeated_hole_patterns(features)", "_extract_repeated_hole_patterns(features, config=resolved)")

    # 3. _extract_axis_aligned_box_features
    content = content.replace("""def _extract_axis_aligned_box_features(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    normal_axis_threshold: float,
    boundary_tolerance_ratio: float,
) -> list[dict[str, Any]]:""", """def _extract_axis_aligned_box_features(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    config: DetectorConfig,
) -> list[dict[str, Any]]:""")
    content = content.replace("normals @ -axis >= normal_axis_threshold", "normals @ -axis >= config.normal_axis_threshold")
    content = content.replace("normals @ axis >= normal_axis_threshold", "normals @ axis >= config.normal_axis_threshold")
    content = content.replace("diagonal * boundary_tolerance_ratio", "diagonal * config.boundary_tolerance_ratio")
    
    # 4. _tolerant_plate_confidence call
    content = content.replace("""    tolerant_plate_confidence = _tolerant_plate_confidence(
        boundary_support,
        bbox,
        total_area,
        size,
    )""", """    tolerant_plate_confidence = _tolerant_plate_confidence(
        boundary_support,
        bbox,
        total_area,
        size,
        config=config,
    )""")
    # 5. _tolerant_box_confidence call
    content = content.replace("""    tolerant_box_confidence = _tolerant_box_confidence(
        boundary_support,
        total_area,
        size,
    )""", """    tolerant_box_confidence = _tolerant_box_confidence(
        boundary_support,
        total_area,
        size,
        config=config,
    )""")

    # 6. box conditions
    content = content.replace("paired_axes >= 2 and confidence >= 0.55 and thin_ratio <= 0.18", "paired_axes >= config.plate_paired_axes_min and confidence >= config.plate_confidence_min and thin_ratio <= config.plate_thin_ratio_max")
    content = content.replace("tolerant_plate_confidence >= 0.70", "tolerant_plate_confidence >= config.plate_tolerant_confidence_min")
    content = content.replace("tolerant_plate_confidence < 0.70", "tolerant_plate_confidence < config.plate_tolerant_confidence_min")
    content = content.replace("paired_axes == 3 and confidence >= 0.80", "paired_axes == config.box_paired_axes_required and confidence >= config.box_confidence_min")
    content = content.replace("tolerant_box_confidence >= 0.70", "tolerant_box_confidence >= config.box_tolerant_confidence_min")
    content = content.replace("tolerant_box_confidence < 0.70", "tolerant_box_confidence < config.box_tolerant_confidence_min")

    # 7. _tolerant_plate_confidence def and body
    content = content.replace("""def _tolerant_plate_confidence(
    boundary_support: dict[str, dict[str, Any]],
    bbox: dict[str, float],
    total_area: float,
    size: list[float],
) -> float:""", """def _tolerant_plate_confidence(
    boundary_support: dict[str, dict[str, Any]],
    bbox: dict[str, float],
    total_area: float,
    size: list[float],
    config: DetectorConfig,
) -> float:""")
    content = content.replace("paired_support_ratio < 0.55", "paired_support_ratio < config.tolerant_plate_paired_support_min")
    content = content.replace("min_span_ratio < 0.75", "min_span_ratio < config.tolerant_plate_min_span_ratio")
    content = content.replace("footprint_area_ratio < 0.60", "footprint_area_ratio < config.tolerant_plate_footprint_area_ratio")
    content = content.replace("footprint_fill_ratio < 0.85", "footprint_fill_ratio < config.tolerant_plate_footprint_fill_ratio")

    # 8. _tolerant_box_confidence def and body
    content = content.replace("""def _tolerant_box_confidence(
    boundary_support: dict[str, dict[str, Any]],
    total_area: float,
    size: list[float],
) -> float:""", """def _tolerant_box_confidence(
    boundary_support: dict[str, dict[str, Any]],
    total_area: float,
    size: list[float],
    config: DetectorConfig,
) -> float:""")
    content = content.replace("min_span_ratio < 0.68", "min_span_ratio < config.tolerant_box_min_span_ratio")
    content = content.replace("footprint_area_ratio < 0.50", "footprint_area_ratio < config.tolerant_box_footprint_area_ratio")
    content = content.replace("footprint_fill_ratio < 0.94", "footprint_fill_ratio < config.tolerant_box_footprint_fill_ratio")
    content = content.replace("overall_support_ratio < 0.60", "overall_support_ratio < config.tolerant_box_overall_support_ratio")

    # 9. _extract_axis_aligned_through_holes def
    content = content.replace("""def _extract_axis_aligned_through_holes(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    existing_features: list[dict[str, Any]],
    normal_axis_threshold: float,
) -> list[dict[str, Any]]:""", """def _extract_axis_aligned_through_holes(
    vectors: np.ndarray,
    normals: np.ndarray,
    face_areas: np.ndarray,
    bbox: dict[str, float],
    existing_features: list[dict[str, Any]],
    config: DetectorConfig,
) -> list[dict[str, Any]]:""")
    content = content.replace("np.abs(normals @ axis_vector) <= (1.0 - normal_axis_threshold)", "np.abs(normals @ axis_vector) <= (1.0 - config.normal_axis_threshold)")
    content = content.replace("boundary_margin = axis_span * 0.05", "boundary_margin = axis_span * config.hole_interior_boundary_margin_ratio")
    content = content.replace("cutout_depth * 0.05\n        ) & (face_centers[:, cutout_axis_index] < span_max - cutout_depth * 0.05)", "cutout_depth * config.hole_interior_depth_margin_ratio\n        ) & (face_centers[:, cutout_axis_index] < span_max - cutout_depth * config.hole_interior_depth_margin_ratio)")
    
    # holes component check
    content = content.replace("len(face_indices) < 8:", "len(face_indices) < config.hole_min_component_faces:")
    
    # holes min max radius
    content = content.replace("max(min(target[\"size\"][axis] for axis in plane_axes) * 0.005, 0.05)", "max(min(target[\"size\"][axis] for axis in plane_axes) * config.hole_min_radius_ratio, 0.05)")
    content = content.replace("max(target[\"size\"][axis] for axis in plane_axes) * 0.45", "max(target[\"size\"][axis] for axis in plane_axes) * config.hole_max_radius_ratio")
    content = content.replace("height_span < cutout_depth * 0.10", "height_span < cutout_depth * config.hole_height_span_floor_ratio")
    
    # counterbore call
    content = content.replace("""            cbore = _try_counterbore_fit(
                component_vertices,
                cutout_axis_index,
                plane_axes,
                cutout_depth,
                span_min,
                span_max,
            )""", """            cbore = _try_counterbore_fit(
                component_vertices,
                cutout_axis_index,
                plane_axes,
                cutout_depth,
                span_min,
                span_max,
                config=config,
            )""")
    # counterbore thresholds in through_holes
    content = content.replace("cbore[\"confidence\"] >= 0.70", "cbore[\"confidence\"] >= config.cbore_angular_coverage_min")
    
    content = content.replace("edge_factor=0.05", "edge_factor=config.hole_edge_factor")
    
    content = content.replace("height_span >= cutout_depth * 0.65", "height_span >= cutout_depth * config.hole_height_span_ratio_min")
    content = content.replace("radial_error_ratio <= 0.08", "radial_error_ratio <= config.hole_radial_error_max")
    content = content.replace("angular_coverage >= 0.70", "angular_coverage >= config.hole_angular_coverage_min")
    content = content.replace("radial_error_ratio / 0.08", "radial_error_ratio / config.hole_radial_error_max")

    content = content.replace("slot_error_ratio / 0.12", "slot_error_ratio / config.slot_error_ratio_max")
    
    content = content.replace("""            slot_fit = _fit_axis_aligned_slot_2d(coords_2d)""", """            slot_fit = _fit_axis_aligned_slot_2d(coords_2d, config=config)""")
    content = content.replace("""            rect_fit = _fit_axis_aligned_rectangle_2d(coords_2d)""", """            rect_fit = _fit_axis_aligned_rectangle_2d(coords_2d, config=config)""")

    content = content.replace("cutout_depth * 0.08", "cutout_depth * config.rect_edge_tolerance_ratio")
    content = content.replace("cutout_depth * 0.10 <=", "cutout_depth * config.pocket_height_floor_ratio <=")
    content = content.replace("<= cutout_depth * 0.95", "<= cutout_depth * config.pocket_height_ceiling_ratio")
    
    # 10. _candidate_cutout_axes
    content = content.replace("""def _candidate_cutout_axes(
    existing_features: list[dict[str, Any]],
) -> list[dict[str, Any]]:""", """def _candidate_cutout_axes(
    existing_features: list[dict[str, Any]],
    config: DetectorConfig,
) -> list[dict[str, Any]]:""")
    content = content.replace("_candidate_cutout_axes(existing_features)", "_candidate_cutout_axes(existing_features, config=config)")

    # 11. _extract_repeated_hole_patterns
    content = content.replace("""def _extract_repeated_hole_patterns(
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:""", """def _extract_repeated_hole_patterns(
    features: list[dict[str, Any]],
    config: DetectorConfig,
) -> list[dict[str, Any]]:""")
    content = content.replace("round(diameter * 100.0)", "round(diameter / config.pattern_diameter_rounding_mm)")
    content = content.replace("diameter_key / 100.0", "diameter_key * config.pattern_diameter_rounding_mm")
    content = content.replace("len(group) >= 4", "len(group) >= config.grid_pattern_min_holes")
    content = content.replace("""            pattern.update(_linear_hole_pattern_metadata(centers, varying_axes))""", """            pattern.update(_linear_hole_pattern_metadata(centers, varying_axes, config=config))""")
    content = content.replace("""            pattern.update(_grid_hole_pattern_metadata(centers, axis, varying_axes))""", """            pattern.update(_grid_hole_pattern_metadata(centers, axis, varying_axes, config=config))""")

    # 12. _linear_hole_pattern_metadata
    content = content.replace("""def _linear_hole_pattern_metadata(
    centers: np.ndarray,
    varying_axes: list[int],
) -> dict[str, Any]:""", """def _linear_hole_pattern_metadata(
    centers: np.ndarray,
    varying_axes: list[int],
    config: DetectorConfig,
) -> dict[str, Any]:""")
    content = content.replace("regularity_error > 0.08", "regularity_error > config.pattern_regularity_error_max")

    # 13. _grid_hole_pattern_metadata
    content = content.replace("""def _grid_hole_pattern_metadata(
    centers: np.ndarray,
    axis: str,
    varying_axes: list[int],
) -> dict[str, Any]:""", """def _grid_hole_pattern_metadata(
    centers: np.ndarray,
    axis: str,
    varying_axes: list[int],
    config: DetectorConfig,
) -> dict[str, Any]:""")

    # 14. _try_counterbore_fit
    content = content.replace("""def _try_counterbore_fit(
    component_vertices: np.ndarray,
    cutout_axis_index: int,
    plane_axes: list[int],
    height_span: float,
    span_min: float,
    span_max: float,
) -> Optional[dict[str, Any]]:""", """def _try_counterbore_fit(
    component_vertices: np.ndarray,
    cutout_axis_index: int,
    plane_axes: list[int],
    height_span: float,
    span_min: float,
    span_max: float,
    config: DetectorConfig,
) -> Optional[dict[str, Any]]:""")
    content = content.replace("h_span < height_span * 0.5:", "h_span < height_span * config.cbore_height_span_floor_ratio:")
    content = content.replace("for slice_ratio in (0.10, 0.15, 0.20):", "for slice_ratio in config.cbore_slice_ratios:")
    content = content.replace("lower_error > 0.12 or upper_error > 0.12", "lower_error > config.cbore_radial_error_max or upper_error > config.cbore_radial_error_max")
    content = content.replace("lower_coverage < 0.60 or upper_coverage < 0.60", "lower_coverage < config.cbore_angular_coverage_min or upper_coverage < config.cbore_angular_coverage_min")
    content = content.replace("larger_radius * 0.10:", "larger_radius * config.cbore_concentric_ratio_max:")
    content = content.replace("radius_ratio < 1.20", "radius_ratio < config.cbore_radius_ratio_min")
    content = content.replace("bore_depth < total_depth * 0.10", "bore_depth < total_depth * config.cbore_depth_floor_ratio")
    content = content.replace("through_depth < total_depth * 0.10", "through_depth < total_depth * config.cbore_depth_floor_ratio")
    content = content.replace("bore_depth > total_depth * 0.95", "bore_depth > total_depth * config.cbore_depth_ceiling_ratio")
    content = content.replace("through_depth > total_depth * 0.95", "through_depth > total_depth * config.cbore_depth_ceiling_ratio")
    content = content.replace("edge_tolerance = total_depth * 0.08", "edge_tolerance = total_depth * config.cbore_edge_tolerance_ratio")
    content = content.replace("worst_error / 0.10", "worst_error / config.cbore_radial_error_max")

    # 15. _fit_axis_aligned_rectangle_2d
    content = content.replace("""def _fit_axis_aligned_rectangle_2d(
    points: np.ndarray,
) -> Optional[tuple[np.ndarray, float, float, float]]:""", """def _fit_axis_aligned_rectangle_2d(
    points: np.ndarray,
    config: DetectorConfig,
) -> Optional[tuple[np.ndarray, float, float, float]]:""")
    content = content.replace("rectangle_error_ratio > 0.04", "rectangle_error_ratio > config.rect_error_ratio_max")
    content = content.replace("min_span * 0.08", "min_span * config.rect_edge_tolerance_ratio")
    content = content.replace("rectangle_error_ratio / 0.04", "rectangle_error_ratio / config.rect_error_ratio_max")

    # 16. _fit_axis_aligned_slot_2d
    content = content.replace("""def _fit_axis_aligned_slot_2d(
    points: np.ndarray,
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, int]]:""", """def _fit_axis_aligned_slot_2d(
    points: np.ndarray,
    config: DetectorConfig,
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, int]]:""")
    content = content.replace("length / width < 1.40", "length / width < config.slot_aspect_ratio_min")
    content = content.replace("straight_length <= radius * 0.25", "straight_length <= radius * config.slot_straight_length_min_ratio")
    content = content.replace("slot_error_ratio > 0.16", "slot_error_ratio > config.slot_error_ratio_max")
    content = content.replace("cap_tolerance = radius * 0.25", "cap_tolerance = radius * config.slot_cap_tolerance_ratio")
    content = content.replace("side_tolerance = radius * 0.25", "side_tolerance = radius * config.slot_side_tolerance_ratio")

    # 17. _center_near_outer_boundary
    content = content.replace("""def _center_near_outer_boundary(
    center_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
    radius: float,
    edge_factor: float = 0.1,
) -> bool:""", """def _center_near_outer_boundary(
    center_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
    radius: float,
    config: DetectorConfig,
    edge_factor: Optional[float] = None,
) -> bool:
    if edge_factor is None:
        edge_factor = config.hole_edge_factor""")
    content = content.replace("""_center_near_outer_boundary(center_2d, bbox, plane_axes, radius)""", """_center_near_outer_boundary(center_2d, bbox, plane_axes, radius, config=config)""")
    content = content.replace("""_center_near_outer_boundary(
                    cbore["center_2d"],
                    bbox,
                    plane_axes,
                    cbore["bore_radius"],
                    edge_factor=0.05,
                )""", """_center_near_outer_boundary(
                    cbore["center_2d"],
                    bbox,
                    plane_axes,
                    cbore["bore_radius"],
                    config=config,
                    edge_factor=0.05,
                )""")

    # 18. _rectangle_near_outer_boundary
    content = content.replace("""def _rectangle_near_outer_boundary(
    center_2d: np.ndarray,
    spans_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
) -> bool:""", """def _rectangle_near_outer_boundary(
    center_2d: np.ndarray,
    spans_2d: np.ndarray,
    bbox: dict[str, float],
    plane_axes: list[int],
    config: DetectorConfig,
) -> bool:""")
    content = content.replace("""_rectangle_near_outer_boundary(
                center_2d,
                np.asarray([width, length], dtype=np.float64),
                bbox,
                plane_axes,
            )""", """_rectangle_near_outer_boundary(
                center_2d,
                np.asarray([width, length], dtype=np.float64),
                bbox,
                plane_axes,
                config=config,
            )""")

    # 19. _slot_near_outer_boundary
    content = content.replace("""def _slot_near_outer_boundary(
    start_2d: np.ndarray,
    end_2d: np.ndarray,
    radius: float,
    bbox: dict[str, float],
    plane_axes: list[int],
) -> bool:""", """def _slot_near_outer_boundary(
    start_2d: np.ndarray,
    end_2d: np.ndarray,
    radius: float,
    bbox: dict[str, float],
    plane_axes: list[int],
    config: DetectorConfig,
) -> bool:""")
    content = content.replace("""_slot_near_outer_boundary(
                        start_2d,
                        end_2d,
                        radius,
                        bbox,
                        plane_axes,
                    )""", """_slot_near_outer_boundary(
                        start_2d,
                        end_2d,
                        radius,
                        bbox,
                        plane_axes,
                        config=config,
                    )""")

    return content

with open("stl2scad/core/feature_graph.py", "r", encoding="utf-8") as f:
    text = f.read()

new_text = modify(text)

with open("stl2scad/core/feature_graph.py", "w", encoding="utf-8") as f:
    f.write(new_text)
