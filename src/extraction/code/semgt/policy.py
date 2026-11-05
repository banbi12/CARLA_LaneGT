"""Metric observation rules and bridge-only constraints; no map paint filtering."""
DEFAULT = dict(
    border_px=48, ground_min_z=-.08, ground_max_z=.4,
    minimum_stroke_length_m=.45, maximum_thin_width_m=.24,
    maximum_local_bend_deg=55., compact_span_m=8., grid_junctions=6,
    curb_distance_m=.85, curb_fraction=.7,
    stripe_seed_radius_m=.12, stripe_min_length_m=1., stripe_max_length_m=7.,
    stripe_min_width_m=.24, stripe_max_width_m=.9, stripe_min_aspect=2.4,
    stripe_min_fill=.7, stripe_min_count=3, stripe_parallel_dot=.96,
    stripe_min_gap_m=.3, stripe_max_gap_m=1.4, stripe_longitudinal_offset_m=.5,
    double_min_spacing_m=.08, double_max_spacing_m=.65,
    double_max_width_variation_m=.1, double_min_overlap_m=.5,
    dash_max_observed_run_m=3.5, dash_min_gap_m=.35, dash_max_gap_m=8.,
    dash_min_tangent_chord_dot=.7, dash_min_mutual_dot=.2,
    dash_max_curve_chord_ratio=1.35, dash_min_road_fraction=.98,
    dash_max_unknown_length_m=.12, small_gap_max_m=.35,
    endpoint_fragment_max_length_m=.35,endpoint_fragment_contact_m=.25,endpoint_fragment_extent_m=.6,
    dash_extension_max_observed_run_m=6.,dash_extension_tangent_dot=.96,dash_extension_gap_relative_tolerance=.2,
    connection_guards_enabled=True, connection_use_xodr=True,
    dash_straight_max_gap_m=9., dash_straight_max_angle_deg=5.,
    dash_straight_max_lateral_m=.20, dash_straight_min_observed_runs=3,
    dash_fragment_guard_min_gap_m=1., dash_fragment_parent_min_span_m=8.,
    dash_fragment_parent_length_ratio=4.,
    dash_xodr_min_gap_m=3., dash_xodr_uncertain_angle_deg=15.,
    dash_xodr_endpoint_distance_m=.6, dash_xodr_endpoint_angle_deg=25.,
    dash_xodr_endpoint_margin_m=.2, dash_xodr_bridge_max_deviation_m=1.25,
    dash_xodr_bad_run_m=.5,
    connection_xodr_required_gap_m=6.,connection_xodr_route_geometry=True,
    connection_xodr_route_max_length_factor=2.,
    divider_base_mode='xodr_v41',divider_base_min_length_m=.35,
    divider_base_min_supplement_m=.5,divider_base_coverage_m=.20,
    divider_base_duplicate_coverage=.90,divider_base_supplement_coverage=.10,
    divider_base_parallel_m=.35,divider_base_parallel_fraction=.80,
    divider_base_double_yellow_m=.50,divider_base_extension_m=1.,
    divider_base_smooth_enabled=True,divider_base_smooth_max_gap_m=2.,
    divider_base_smooth_min_gap_m=.02,divider_base_smooth_max_curve_ratio=2.,
    divider_base_smooth_tangent_dot=.20,divider_base_merge_endpoint_m=.10,
    boundary_smooth_enabled=True,boundary_smooth_max_gap_m=1.5,
    boundary_smooth_min_tangent_dot=.20,boundary_smooth_max_curve_ratio=1.5,
)

def checked(overrides=None):
    policy = dict(DEFAULT)
    if overrides:
        unknown = set(overrides)-set(policy)
        if unknown:
            raise ValueError('Unknown policy keys: '+str(sorted(unknown)))
        policy.update(overrides)
    if policy['small_gap_max_m'] != .35:
        raise ValueError('The adopted small-gap scope is fixed at 0.35m')
    if not 0 < policy['dash_min_gap_m'] < policy['dash_max_gap_m'] <= 8:
        raise ValueError('Invalid dash gap range')
    if not policy['dash_max_gap_m'] <= policy['dash_straight_max_gap_m'] <= 9:
        raise ValueError('Only conditional straight gaps may extend to 9m')
    if not 0 < policy['dash_straight_max_angle_deg'] <= 10 or not 0 < policy['dash_straight_max_lateral_m'] <= .3:
        raise ValueError('Invalid conservative straight-connection geometry')
    if not 0 <= policy['connection_xodr_required_gap_m'] < policy['dash_max_gap_m']:
        raise ValueError('Invalid XODR route-required gap')
    if policy['connection_xodr_route_max_length_factor'] < 1:
        raise ValueError('Invalid XODR route length factor')
    if policy['divider_base_mode'] not in ('semantic','xodr_v41'):
        raise ValueError('Invalid divider base mode')
    if not .35 < policy['boundary_smooth_max_gap_m'] <= 2.:
        raise ValueError('Invalid boundary smooth gap')
    if not 0 <= policy['boundary_smooth_min_tangent_dot'] <= 1:
        raise ValueError('Invalid boundary smooth tangent threshold')
    if not 1 <= policy['boundary_smooth_max_curve_ratio'] <= 3:
        raise ValueError('Invalid boundary smooth curve ratio')
    return policy
