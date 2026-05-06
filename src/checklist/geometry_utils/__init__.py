"""Geometry utilities for checklist rules.

This package replaces the monolithic geometry_utils.py.  All public names
are re-exported here so existing rule imports of the form:

    from src.checklist.geometry_utils import <name>

continue to work without modification.
"""

from .polygon import (
    _outline_vertices,
    _outline_to_shapely,
    _resolve_footprint,
    _resolve_outline,
    _get_pad_centers,
    get_component_footprint,
    get_component_outline,
    is_on_edge,
)

from .orientation import (
    get_component_orientation,
    get_major_axis_angle,
    get_pair_orientation,
    are_components_aligned,
)

from .overlap import (
    _get_pad_union,
    _get_outermost_pad_union,
    _symbol_to_shapely,
    _user_symbol_to_shapely,
    find_outermost_pin_indices,
    find_overlapping_components,
    find_outermost_pad_overlapping_components,
    find_pad_overlapping_components,
    find_components_inside_outline,
    overlaps_component_outline,
    is_sandwiched_between,
    has_empty_center,
    find_empty_center_ics,
)

from .distance import (
    center_distance,
    edge_distance,
    load_component_list,
    filter_components_by_list,
)

from .size import (
    get_component_size,
    size_at_least,
    filter_by_size,
)

from .clearance import (
    build_board_polygon,
    build_inset_boundary,
    distance_to_outline,
    pad_distance_to_outline,
    pad_distance_to_component,
    pad_to_pad_distance,
    components_in_clearance_zone,
    components_with_pads_in_clearance_zone,
    signal_features_in_clearance_zone,
)

from .via import (
    build_via_position_set,
    build_toeprint_lookup,
    lookup_resolved_pads_for_pin,
    count_vias_at_pad,
    _get_pad_polygon_board,
    _resolved_pad_polygon,
)

from .bending import (
    find_bending_vulnerable_areas,
)

from .nc_pad import (
    is_pad_nc,
)

from .shield_can import (
    is_on_corner_or_diagonal,
    get_orientation_relative_to_shield_can,
    find_outline_boundary_pad_overlapping_components,
    get_orientation_relative_to_outline_edge,
    detect_inner_walls,
    find_nearest_inner_wall,
    is_near_inner_wall,
    detect_fill_cuts,
)
