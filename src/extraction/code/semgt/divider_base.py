"""Fuse XODR-only V4.1 divider base with semantic observation supplements."""
from __future__ import annotations

import copy

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .geometry import uid

RULE = "xodr_v41_base_semantic_supplement_v1"


def _line(feature):
    points = np.asarray(feature["points_xyz"], float)
    if points.ndim != 2 or len(points) < 2:
        return None
    line = LineString(points[:, :2])
    return line if line.length > 1e-8 else None


def _parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    return [part for part in getattr(geometry, "geoms", []) if part.geom_type == "LineString"]


def _is_double_yellow(feature):
    source = feature.get("source")
    if source == "observed_double_yellow_midcurve":
        return True
    return isinstance(source, dict) and source.get("kind") == "observed_double_yellow_midcurve"


def _parallel_duplicate(line, lines, tolerance, fraction):
    if not lines or line.length <= 1e-8:
        return False
    count = max(2, int(np.ceil(line.length / 0.5)) + 1)
    points = [Point(line.interpolate(float(s))) for s in np.linspace(0, line.length, count)]
    for other in lines:
        support = sum(other.distance(point) <= tolerance for point in points) / len(points)
        if support >= fraction:
            return True
    return False


def _supplement_source(feature, coverage, reason):
    source = copy.deepcopy(feature.get("source"))
    fields = dict(semantic_supplement=True, base_coverage=round(float(coverage), 5),
                  supplement_reason=reason)
    if isinstance(source, dict):
        source.update(fields)
        return source
    return dict(kind=source, **fields)


def _dedupe(points):
    array = np.asarray(points, float)
    if len(array) == 0:
        return array
    out = [array[0]]
    for point in array[1:]:
        if float(np.linalg.norm(point - out[-1])) > 1e-9:
            out.append(point)
    return np.asarray(out)


def _smooth_connector(points, at_start, base_lines, base_ids, policy):
    """Return a short Hermite connector from a supplement endpoint to a base line."""
    from .geometry import bridge

    point = points[0] if at_start else points[-1]
    gap_max = float(policy["divider_base_smooth_max_gap_m"])
    gap_min = float(policy["divider_base_smooth_min_gap_m"])
    max_ratio = float(policy["divider_base_smooth_max_curve_ratio"])
    min_dot = float(policy["divider_base_smooth_tangent_dot"])
    candidates = []
    for index, base_line in enumerate(base_lines):
        distance = float(base_line.distance(Point(point)))
        if gap_min <= distance <= gap_max:
            candidates.append((distance, index, base_line))
    if not candidates:
        return None
    distance, index, base_line = min(candidates, key=lambda item: item[0])
    position = float(base_line.project(Point(point)))
    base_point = np.asarray(base_line.interpolate(position).coords[0], float)
    delta = min(1.0, max(0.2, base_line.length * 0.1))
    position2 = position + delta if position + delta <= base_line.length else position - delta
    base_next = np.asarray(base_line.interpolate(position2).coords[0], float)
    if len(points) < 2:
        return None
    if at_start:
        pa = np.vstack([points[1], points[0]])
        direction = points[0] - points[1]
    else:
        pa = np.vstack([points[-2], points[-1]])
        direction = points[-1] - points[-2]
    direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
    if float((base_next - base_point) @ direction) < 0:
        position2 = position - delta
        base_next = np.asarray(base_line.interpolate(position2).coords[0], float)
    if float(np.linalg.norm(base_next - base_point)) < 1e-9:
        position2 = position - delta if position2 > position else position + delta
        base_next = np.asarray(base_line.interpolate(position2).coords[0], float)
    if float(np.linalg.norm(base_next - base_point)) < 1e-9:
        return None
    pb = np.vstack([base_point, base_next])
    chord = (base_point - np.asarray(point, float))
    chord /= max(float(np.linalg.norm(chord)), 1e-12)
    if float(direction @ chord) < min_dot:
        return None
    curve, _, _ = bridge(pa, pb)
    curve = np.asarray(curve, float)[:, :2]
    if len(curve) < 2 or LineString(curve).length > distance * max_ratio:
        return None
    if not LineString(curve).is_simple:
        return None
    connector = curve[::-1] if at_start else curve
    return connector, dict(base_id=base_ids[index], gap_m=round(distance, 5),
                           base_line_distance_m=round(distance, 5))


def smooth_supplement_connections(features, base_lines, base_ids, policy):
    """Blend semantic supplement endpoints into nearby V4.1 base lines."""
    if not policy.get("divider_base_smooth_enabled") or not base_lines:
        return features, dict(rule="xodr_v41_semantic_smooth_connector_v1",
                              enabled=False, supplements=0, connections=0)
    summary = dict(rule="xodr_v41_semantic_smooth_connector_v1", enabled=True,
                   supplements=0, connections=0, max_gap_m=0.0)
    for feature in features:
        source = feature.get("source")
        if not (isinstance(source, dict) and source.get("semantic_supplement")):
            continue
        points = np.asarray(feature["points_xyz"], float)[:, :2]
        if len(points) < 2:
            continue
        summary["supplements"] += 1
        start = _smooth_connector(points, True, base_lines, base_ids, policy)
        end = _smooth_connector(points, False, base_lines, base_ids, policy)
        if start is None and end is None:
            continue
        pieces = []
        records = []
        if start is not None:
            pieces.append(start[0])
            records.append(dict(side="start", **start[1]))
        pieces.append(points)
        if end is not None:
            pieces.append(end[0])
            records.append(dict(side="end", **end[1]))
        joined = _dedupe(np.vstack(pieces))
        if len(joined) < 2 or not LineString(joined).is_simple:
            continue
        feature["points_xyz"] = [[float(x), float(y), 0.0] for x, y in joined]
        source["smooth_connections"] = records
        summary["connections"] += len(records)
        summary["max_gap_m"] = max(summary["max_gap_m"], max(record["gap_m"] for record in records))
    return features, summary


def merge_connected_supplements(features, policy):
    """Merge a supplement into its base when it attaches at a base endpoint.

    Only supplements with exactly one smooth-connection record are considered.
    This conservatively turns an endpoint extension into one divider feature so
    MapTRv2 samples it once, instead of sampling base and supplement separately.
    """
    base_by_id = {}
    for feature in features:
        source = feature.get("source")
        if isinstance(source, dict) and source.get("xodr_v41_base"):
            base_by_id[feature.get("id")] = feature
    groups = {}
    for feature in features:
        source = feature.get("source")
        if not (isinstance(source, dict) and source.get("semantic_supplement")):
            continue
        records = source.get("smooth_connections") or []
        if len(records) != 1:
            continue
        record = records[0]
        base = base_by_id.get(record.get("base_id"))
        if base is None:
            continue
        points = np.asarray(feature["points_xyz"], float)[:, :2]
        base_points = np.asarray(base["points_xyz"], float)[:, :2]
        attachment = points[0] if record.get("side") == "start" else points[-1]
        d_start = float(np.linalg.norm(attachment - base_points[0]))
        d_end = float(np.linalg.norm(attachment - base_points[-1]))
        tolerance = float(policy["divider_base_merge_endpoint_m"])
        if min(d_start, d_end) > tolerance:
            continue
        slot = "start" if d_start <= d_end else "end"
        groups.setdefault(base["id"], {"start": [], "end": []})[slot].append((feature, record, points))

    remove = set()
    merged = []
    audit = dict(rule="xodr_v41_connected_supplement_merge_v1",
                 bases_considered=len(groups), bases_merged=0,
                 supplements_merged=0, candidates_skipped=0,
                 before=len(features), after=len(features))
    for base_id, slots in groups.items():
        if len(slots["start"]) > 1 or len(slots["end"]) > 1:
            audit["candidates_skipped"] += len(slots["start"]) + len(slots["end"])
            continue
        start = slots["start"][0] if slots["start"] else None
        end = slots["end"][0] if slots["end"] else None
        if start is None and end is None:
            continue
        base = base_by_id[base_id]
        pieces = []
        supplement_ids = []
        if start is not None:
            feature, record, points = start
            oriented = points[::-1] if record.get("side") == "start" else points
            pieces.append(oriented)
            supplement_ids.append(feature.get("id"))
        pieces.append(np.asarray(base["points_xyz"], float)[:, :2])
        if end is not None:
            feature, record, points = end
            oriented = points if record.get("side") == "start" else points[::-1]
            pieces.append(oriented)
            supplement_ids.append(feature.get("id"))
        combined = _dedupe(np.vstack(pieces))
        if len(combined) < 2 or not LineString(combined).is_simple:
            audit["candidates_skipped"] += len(supplement_ids)
            continue
        item = copy.deepcopy(base)
        item["id"] = uid(combined, "divider_merged")
        item["points_xyz"] = [[float(x), float(y), 0.0] for x, y in combined]
        if isinstance(item.get("source"), dict):
            item["source"].update(
                divider_target_merge=True, merge_rule=audit["rule"],
                merged_base_id=base_id, merged_supplement_ids=supplement_ids,
            )
        merged.append(item)
        remove.add(base_id)
        for feature_id in supplement_ids:
            remove.add(feature_id)
        audit["bases_merged"] += 1
        audit["supplements_merged"] += len(supplement_ids)
    result = [feature for feature in features if feature.get("id") not in remove] + merged
    audit["after"] = len(result)
    return result, audit


def merge_divider_base(base_features, semantic_features, policy):
    """Keep V4.1 base lines and add only semantic geometry absent from the base."""
    min_base = float(policy["divider_base_min_length_m"])
    min_supplement = float(policy["divider_base_min_supplement_m"])
    tolerance = float(policy["divider_base_coverage_m"])
    duplicate_coverage = float(policy["divider_base_duplicate_coverage"])
    supplement_coverage = float(policy["divider_base_supplement_coverage"])
    parallel_tolerance = float(policy["divider_base_parallel_m"])
    parallel_fraction = float(policy["divider_base_parallel_fraction"])
    yellow_tolerance = float(policy["divider_base_double_yellow_m"])
    extension_m = float(policy["divider_base_extension_m"])

    base, dropped_short = [], []
    base_pairs = []
    for feature in base_features:
        line = _line(feature)
        if line is None:
            continue
        if line.length < min_base:
            dropped_short.append(dict(id=feature.get("id"), length_m=round(line.length, 4)))
            continue
        item = copy.deepcopy(feature)
        base.append(item)
        base_pairs.append((item, line))
    base_lines = [line for _, line in base_pairs]
    base_buffer = unary_union([line.buffer(tolerance) for line in base_lines]) if base_lines else None
    yellow_lines = [
        line for feature, line in base_pairs
        if isinstance(feature.get("source"), dict) and feature["source"].get("mark_color") == "yellow"
    ]

    supplements = []
    audit = dict(rule=RULE, base_input=len(base_features), base_kept=len(base),
                 base_dropped_short=len(dropped_short), semantic_input=len(semantic_features),
                 semantic_non_divider_skipped=0, semantic_duplicate=0,
                 semantic_parallel_duplicate=0, semantic_double_yellow_duplicate=0,
                 semantic_full_supplement=0, semantic_partial_supplement=0,
                 semantic_bridge_dropped=0, semantic_empty_supplement=0, output_count=0)
    for feature in semantic_features:
        if feature.get("class_name") != "divider":
            audit["semantic_non_divider_skipped"] += 1
            continue
        line = _line(feature)
        if line is None:
            continue
        if base_buffer is None:
            coverage = 0.0
        else:
            coverage = float(line.intersection(base_buffer).length / line.length)
        if _is_double_yellow(feature) and _parallel_duplicate(
                line, yellow_lines, yellow_tolerance, parallel_fraction):
            audit["semantic_double_yellow_duplicate"] += 1
            continue
        if base_buffer is None or coverage <= supplement_coverage:
            item = copy.deepcopy(feature)
            item["source"] = _supplement_source(feature, coverage, "no_base_support")
            item["review"] = "pending"
            supplements.append(item)
            audit["semantic_full_supplement"] += 1
            continue

        extensions, bridges = [], 0
        for part in _parts(line.difference(base_buffer)):
            if part.length < min_supplement:
                continue
            start = float(line.project(Point(part.coords[0])))
            end = float(line.project(Point(part.coords[-1])))
            at_end = min(start, end) <= extension_m or max(start, end) >= line.length - extension_m
            if at_end:
                extensions.append(part)
            else:
                bridges += 1
        if extensions:
            for part in extensions:
                points = [[float(x), float(y)] for x, y in part.coords]
                identifier = uid(points, "divider_supplement")
                item = dict(id=identifier, class_name="divider",
                            points_xyz=[[float(x), float(y), 0.0] for x, y in part.coords],
                            source=_supplement_source(feature, coverage, "base_endpoint_extension"),
                            review="pending")
                supplements.append(item)
            audit["semantic_partial_supplement"] += len(extensions)
            audit["semantic_bridge_dropped"] += bridges
            continue
        if coverage >= duplicate_coverage:
            audit["semantic_duplicate"] += 1
            continue
        if _parallel_duplicate(line, base_lines, parallel_tolerance, parallel_fraction):
            audit["semantic_parallel_duplicate"] += 1
            continue
        audit["semantic_bridge_dropped"] += bridges
        audit["semantic_empty_supplement"] += 1
    result = base + supplements
    base_ids = [feature.get("id") for feature, _ in base_pairs]
    result, smooth = smooth_supplement_connections(result, base_lines, base_ids, policy)
    audit["smooth_connections"] = smooth
    result, target_merge = merge_connected_supplements(result, policy)
    audit["target_merge"] = target_merge
    audit["output_count"] = len(result)
    audit["base_dropped_short_details"] = dropped_short
    return result, audit
