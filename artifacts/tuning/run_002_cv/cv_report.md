# Cross-Validation Report

- **Mean holdout score**: 0.9948
- **Std dev across folds**: 0.0184

## Per-fold scores

- Fold 1 (held out plate_plain): 1.0000
- Fold 2 (held out plate_plain_chamfered_edges): 1.0000
- Fold 3 (held out plate_plain_rotated_z30): 1.0000
- Fold 4 (held out plate_linear_two_holes): 1.0000
- Fold 5 (held out plate_grid_two_by_three): 1.0000
- Fold 6 (held out plate_single_slot): 1.0000
- Fold 7 (held out plate_rectangular_through_cutout): 1.0000
- Fold 8 (held out plate_rectangular_top_pocket): 1.0000
- Fold 9 (held out plate_single_counterbore): 1.0000
- Fold 10 (held out plate_counterbore_depth_near_thickness): 1.0000
- Fold 11 (held out plate_counterbore_small_clearance): 0.9333
- Fold 12 (held out plate_mixed_linear_and_slot): 1.0000
- Fold 13 (held out plate_multi_pattern_mixed_edge): 1.0000
- Fold 14 (held out plate_near_boundary_linear): 1.0000
- Fold 15 (held out plate_long_aspect_linear): 1.0000
- Fold 16 (held out plate_small_hole_grid): 1.0000
- Fold 17 (held out plate_large_hole_pair): 1.0000
- Fold 18 (held out box_z_through_hole): 1.0000
- Fold 19 (held out box_x_through_hole): 1.0000
- Fold 20 (held out box_rounded_edges): 0.9315
- Fold 21 (held out box_z_through_hole_rotated_z25): 1.0000
- Fold 22 (held out l_bracket_plain): 1.0000
- Fold 23 (held out negative_sphere): 1.0000
- Fold 24 (held out negative_torus): 1.0000
- Fold 25 (held out box_with_top_notch): 1.0000
- Fold 26 (held out box_hollow_ambiguous): 1.0000

## Parameter Stability

A stable parameter is a credible signal. An unstable parameter is overfit.

| Parameter | Min | Max | Span | Mean | Std Dev |
|---|---|---|---|---|---|
| boundary_tolerance_ratio | 0.0064 | 0.0291 | 0.0228 | 0.0163 | 0.0068 |
| box_confidence_min | 0.6252 | 0.8544 | 0.2291 | 0.7099 | 0.0599 |
| box_tolerant_confidence_min | 0.5508 | 0.8440 | 0.2932 | 0.7057 | 0.0953 |
| cbore_angular_coverage_min | 0.4519 | 0.7855 | 0.3335 | 0.6102 | 0.1000 |
| cbore_radial_error_max | 0.0687 | 0.1950 | 0.1263 | 0.1415 | 0.0379 |
| cbore_radius_ratio_min | 1.0509 | 1.4888 | 0.4379 | 1.2889 | 0.1424 |
| hole_angular_coverage_min | 0.5706 | 0.8761 | 0.3055 | 0.7282 | 0.0950 |
| hole_height_span_ratio_min | 0.4579 | 0.7950 | 0.3371 | 0.6008 | 0.1051 |
| hole_max_radius_ratio | 0.3285 | 0.5473 | 0.2189 | 0.4203 | 0.0643 |
| hole_min_radius_ratio | 0.0022 | 0.0194 | 0.0172 | 0.0077 | 0.0050 |
| hole_radial_error_max | 0.0432 | 0.1467 | 0.1034 | 0.0961 | 0.0342 |
| normal_axis_threshold | 0.9042 | 0.9893 | 0.0850 | 0.9402 | 0.0263 |
| pattern_regularity_error_max | 0.0481 | 0.1490 | 0.1008 | 0.1081 | 0.0295 |
| plate_confidence_min | 0.3649 | 0.7460 | 0.3811 | 0.5568 | 0.1112 |
| plate_thin_ratio_max | 0.1123 | 0.2844 | 0.1721 | 0.1906 | 0.0486 |
| plate_tolerant_confidence_min | 0.5553 | 0.7583 | 0.2031 | 0.6614 | 0.0536 |
| rect_error_ratio_max | 0.0241 | 0.0783 | 0.0542 | 0.0493 | 0.0157 |
| slot_aspect_ratio_min | 1.1059 | 1.7506 | 0.6447 | 1.3751 | 0.1938 |
| slot_error_ratio_max | 0.0803 | 0.2450 | 0.1647 | 0.1921 | 0.0514 |
| tolerant_box_footprint_area_ratio | 0.3707 | 0.6960 | 0.3254 | 0.5506 | 0.1036 |
| tolerant_box_footprint_fill_ratio | 0.8512 | 0.9784 | 0.1272 | 0.9169 | 0.0361 |
| tolerant_box_min_span_ratio | 0.5587 | 0.8468 | 0.2881 | 0.6865 | 0.1001 |
| tolerant_box_overall_support_ratio | 0.5094 | 0.7977 | 0.2883 | 0.6371 | 0.0854 |
| tolerant_plate_footprint_area_ratio | 0.4607 | 0.6817 | 0.2210 | 0.5622 | 0.0664 |
| tolerant_plate_footprint_fill_ratio | 0.7005 | 0.9442 | 0.2436 | 0.8161 | 0.0794 |
| tolerant_plate_min_span_ratio | 0.6032 | 0.7998 | 0.1966 | 0.6945 | 0.0652 |
