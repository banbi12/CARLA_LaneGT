"""原版方案 M 三类世界几何函数；删除历史渲染和固定帧 CLI 依赖。"""
from __future__ import annotations
import math
from shapely import set_precision
from shapely.geometry import Polygon,LineString
from shapely.ops import unary_union
from .lanelines import extract_all_segments
from .surface import Strip,_strip_polygon
from .xodr import road_boundaries
BASE_TYPES=frozenset(("driving","biking","parking","bidirectional"))

def shoulder_record(road, section, lane, threshold):
    sample_s = [section.s, (section.s + road.length) / 2, road.length]
    widths = [lane.width_at(s) for s in sample_s]
    outer_marks = sorted({m.type for m in lane.marks})
    include = min(widths) >= threshold
    return {
        "road_id": road.id, "section_s": section.s, "lane_id": lane.id,
        "junction": road.junction, "width_start_m": round(widths[0], 3),
        "width_mid_m": round(widths[1], 3),
        "width_end_m": round(widths[2], 3),
        "outer_mark_types": ",".join(outer_marks),
        "decision": "include_wide_shoulder" if include else "exclude_narrow_shoulder",
        "review_status": "rule_based_requires_visual_audit",
    }


def build_strips(xmap, threshold, step, shoulder_overrides, lane_overrides):
    strips = []
    shoulder_rows = []
    included = set()
    for road in xmap.roads:
        boundaries = {b.lane_id: b for b in road_boundaries(road)}
        for section in road.sections:
            for lane in section.lanes:
                if lane.type == "shoulder":
                    row = shoulder_record(road, section, lane, threshold)
                    override = shoulder_overrides.get((road.id, section.s, lane.id))
                    if override is not None:
                        row["decision"] = override["decision"]
                        row["review_status"] = "reviewed_visual"
                        row["evidence"] = override["evidence"]
                    else:
                        row["evidence"] = ""
                    shoulder_rows.append(row)
                    if row["decision"] == "include_wide_shoulder":
                        included.add((road.id, section.s, lane.id))
            for side, sign in (("left", 1), ("right", -1)):
                lanes = sorted((l for l in section.lanes if l.id * sign > 0),
                               key=lambda l: abs(l.id))
                run = []
                for lane in [*lanes, None]:
                    allowed = lane is not None and (
                        lane.type in BASE_TYPES or
                        (lane.type == "shoulder" and
                         (road.id, section.s, lane.id) in included) or
                        (lane_overrides.get((road.id, section.s, lane.id), {})
                         .get("decision") == "include_drivable_none"))
                    if allowed:
                        run.append(lane)
                        continue
                    if run:
                        first, last = run[0], run[-1]
                        inner_id = 0 if abs(first.id) == 1 else (abs(first.id) - 1) * sign
                        inner, outer = boundaries.get(inner_id), boundaries.get(last.id)
                        if inner is not None and outer is not None:
                            n = max(24, math.ceil(road.length / step) + 1)
                            poly = _strip_polygon(road, inner, outer, n)
                            if poly is not None:
                                strips.append(Strip(road.id, side, [l.id for l in run], poly))
                        run = []
    return strips, shoulder_rows


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for part in getattr(geometry, "geoms", [])
            if part.geom_type == "Polygon"]


def make_surface(strips, grid_m, crosswalks, fill_hole_max_area_m2,
                 hole_fill_overrides):
    source_polys = [set_precision(s.polygon, grid_m) for s in strips]
    merged = unary_union(source_polys)
    crosswalk_polys = [Polygon(ring[:, :2]) for ring in crosswalks]
    hole_decisions = []
    matched_overrides = set()
    filled_parts = []
    for part in polygon_parts(merged):
        retained_holes = []
        for ring in part.interiors:
            hole = Polygon(ring)
            touching = [i for i, crosswalk in enumerate(crosswalk_polys)
                        if hole.intersects(crosswalk)]
            overlap_area = sum(hole.intersection(crosswalk_polys[i]).area
                               for i in touching)
            overrides = [i for i, item in enumerate(hole_fill_overrides)
                         if math.dist((hole.centroid.x, hole.centroid.y),
                                      item["centroid_xy"]) < 0.1]
            if len(overrides) > 1:
                raise ValueError("Multiple fill overrides match one hole")
            matched_overrides.update(overrides)
            fill = hole.area < fill_hole_max_area_m2 and (
                not touching or bool(overrides))
            hole_decisions.append({
                "centroid_xy": [round(hole.centroid.x, 3),
                                round(hole.centroid.y, 3)],
                "area_m2": round(hole.area, 5),
                "crosswalk_indices": touching,
                "crosswalk_overlap_m2": round(overlap_area, 5),
                "crosswalk_overlap_fraction": round(
                    min(1.0, overlap_area / hole.area), 4),
                "decision": "fill_drivable_gap_visual_override" if fill and overrides else
                            "fill_drivable_gap" if fill else
                            "retain_crosswalk_connected_for_review" if touching and
                            hole.area < fill_hole_max_area_m2 else "retain",
                "evidence": hole_fill_overrides[overrides[0]]["evidence"]
                            if overrides else "",
            })
            if not fill:
                retained_holes.append(ring.coords)
        filled_parts.append(Polygon(part.exterior.coords, retained_holes))
    if len(matched_overrides) != len(hole_fill_overrides):
        raise ValueError("A hole fill override did not match this XODR surface")
    merged = unary_union(filled_parts)
    parts = polygon_parts(merged)
    rings = []
    for part_index, poly in enumerate(parts):
        for ring_index, ring in enumerate([poly.exterior, *poly.interiors]):
            line = LineString(ring.coords)
            nearby = []
            for strip in strips:
                if strip.polygon.boundary.distance(line) < 0.05:
                    nearby.append({"road_id": strip.road_id, "side": strip.side,
                                   "lane_ids": strip.lane_ids})
            rings.append({
                "points": [[float(x), float(y)] for x, y in ring.coords],
                "source": {"part_index": part_index, "ring_index": ring_index,
                           "ring_kind": "exterior" if ring_index == 0 else "interior",
                           "area_m2": round(Polygon(ring).area, 5),
                           "nearby_strips": nearby},
            })
    return merged, parts, rings, hole_decisions


def precision_audit(strips, selected_grid):
    checks = []
    for grid in sorted({0.0, 0.001, selected_grid}):
        merged = unary_union([set_precision(s.polygon, grid) for s in strips])
        components = polygon_parts(merged)
        checks.append({
            "grid_m": grid, "components": len(components),
            "area_m2": round(merged.area, 6),
            "component_areas_m2": sorted(
                [round(p.area, 6) for p in components], reverse=True),
            "boundary_length_m": round(merged.boundary.length, 4),
        })
    return checks


def annotation_boundaries(rings, decisions):
    """Split map annotation polylines at audited non-physical road-end caps."""
    excluded = decisions.get("excluded_crosscaps", [])
    matched = [0] * len(excluded)
    result, removed = [], []
    for ring in rings:
        points = ring["points"]
        runs = []
        run = [points[0]]
        for a, b in zip(points, points[1:]):
            hits = [i for i, item in enumerate(excluded)
                    if min(max(math.dist(a, item["endpoints_xy"][0]),
                               math.dist(b, item["endpoints_xy"][1])),
                           max(math.dist(a, item["endpoints_xy"][1]),
                               math.dist(b, item["endpoints_xy"][0]))) < 0.02]
            if len(hits) > 1:
                raise ValueError("A boundary edge matched multiple exclusions")
            if hits:
                index = hits[0]
                matched[index] += 1
                removed.append({"source": ring["source"], "points": [a, b],
                                "evidence": excluded[index]["evidence"]})
                if len(run) > 1:
                    runs.append(run)
                run = [b]
            else:
                run.append(b)
        if len(run) > 1:
            runs.append(run)
        if len(runs) > 1 and runs[-1][-1] == runs[0][0]:
            runs[0] = runs[-1][:-1] + runs[0]
            runs.pop()
        result.extend({"source": ring["source"], "points": points}
                      for points in runs)
    if any(count != 1 for count in matched):
        raise ValueError(f"Boundary exclusion match counts: {matched}")
    return result, removed


def selected_dividers(xmap, surface, interior_margin):
    selected, rejected = [], []
    interior = surface.buffer(-interior_margin)
    for seg in extract_all_segments(xmap, step=0.5, include_unpainted=False):
        line = LineString(seg.points[:, :2])
        if not seg.is_painted or line.length < 0.05:
            continue
        overlap = line.intersection(interior).length / line.length
        source = {
            "road_id": seg.road_id, "lane_id": seg.lane_id, "junction": seg.junction,
            "side": seg.side, "mark_type": seg.mark_type, "mark_color": seg.mark_color,
            "lane_change": seg.lane_change, "s_start": seg.s_start, "s_end": seg.s_end,
            "interior_fraction": round(overlap, 4),
        }
        item = {"source": source, "points": seg.points[:, :2].tolist(),
                "length_m": round(line.length, 4)}
        if overlap >= 0.8:
            selected.append(item)
        else:
            rejected.append(item)
    return selected, rejected
