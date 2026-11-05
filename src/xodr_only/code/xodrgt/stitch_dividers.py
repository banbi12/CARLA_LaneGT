#!/usr/bin/env python3
"""Stitch XODR divider fragments with strong same-paint endpoint continuity.

This is an XODR-only map-geometry stage. It does not read semantic images and it
does not use the V4.2 semantic connection rules. Only same mark type/color
endpoints are joined; solid and broken paint have different gap limits.
"""
from __future__ import annotations

import copy
import math
from typing import Iterable

import numpy as np
from shapely.geometry import LineString, Point

from .xodr_topology import Endpoint

RULE = "xodr_same_paint_endpoint_stitch_v1"


def _tangent(line: LineString, at_start: bool, window: float = 1.0):
    if line.length <= 1e-8:
        return np.zeros(2)
    s = 0.0 if at_start else line.length
    a = line.interpolate(max(0.0, s - window))
    b = line.interpolate(min(line.length, s + window))
    v = np.asarray([b.x - a.x, b.y - a.y], float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _limits(mark_type: str):
    if "broken" in mark_type:
        return 9.0, 0.80, 0.25
    if "solid" in mark_type:
        return 2.0, 0.95, 0.10
    return 2.0, 0.95, 0.10


def _support(line: LineString, surface, margin: float = 0.05):
    if surface is None or surface.is_empty:
        return 1.0
    # Endpoints can sit exactly on the drivable-surface edge after the 0.05m
    # interior selection; use a small outward tolerance for the bridge.
    inner = surface.buffer(margin)
    if inner.is_empty:
        return 0.0
    n = max(2, int(math.ceil(line.length / 0.25)) + 1)
    pts = [line.interpolate(float(s)) for s in np.linspace(0, line.length, n)]
    return float(np.mean([inner.covers(p) for p in pts]))


def _third_line_blocked(bridge: LineString, lines: list[LineString], i: int, j: int):
    # Tiny paint gaps are often surrounded by the next observed fragment at
    # their endpoints. Do not treat endpoint contact as a third-line crossing.
    if bridge.length <= 0.30:
        return False
    inset = min(0.05, bridge.length * 0.10)
    interior = LineString([bridge.interpolate(inset), bridge.interpolate(bridge.length - inset)])
    for k, other in enumerate(lines):
        if k in (i, j):
            continue
        # A true crossing or a substantial overlap blocks the bridge; mere
        # proximity to a parallel line does not.
        if interior.intersects(other) or interior.intersection(other.buffer(0.10)).length > 0.25:
            return True
    return False


def _endpoint_meta(source, side, topology):
    if topology is None:
        return None
    road_id = source.get('road_id')
    lane_id = source.get('lane_id')
    if road_id not in topology.roads or lane_id is None:
        return None
    s = source.get('s_start') if side == 0 else source.get('s_end')
    if s is None:
        return None
    length = topology.roads[road_id].length
    if abs(float(s)) <= 0.5:
        contact = 'start'
    elif abs(float(s) - length) <= 0.5:
        contact = 'end'
    else:
        return None
    return Endpoint(int(road_id), int(lane_id), contact)


def _candidate(a, b, lines, surface, limits, min_gap, ia, ib, topology=None,
               topology_max_gap_m=25.0, geometric_fallback_max_gap_m=0.50):
    type_a, color_a = a["source"].get("mark_type"), a["source"].get("mark_color")
    type_b, color_b = b["source"].get("mark_type"), b["source"].get("mark_color")
    if (type_a, color_a) != (type_b, color_b):
        return None
    max_gap, min_dot, max_lateral = limits
    # Same road/lane fragments may have longer map gaps than a generic
    # intersection bridge. Keep this extension strict and local.
    if ("broken" in type_a and a["source"].get("road_id") == b["source"].get("road_id")
            and a["source"].get("lane_id") == b["source"].get("lane_id")):
        max_gap = max(max_gap, 12.0)
        min_dot = max(min_dot, 0.95)
        max_lateral = min(max_lateral, 0.10)
    pa_all = np.asarray(a["points"], float)[:, :2]
    pb_all = np.asarray(b["points"], float)[:, :2]
    best = None
    for ra in (False, True):
        pa = pa_all[::-1] if ra else pa_all
        if len(pa) < 2:
            continue
        la = LineString(pa)
        ta = _tangent(la, at_start=False)
        for rb in (False, True):
            pb = pb_all[::-1] if rb else pb_all
            if len(pb) < 2:
                continue
            lb = LineString(pb)
            tb = _tangent(lb, at_start=True)
            gap = float(np.linalg.norm(pb[0] - pa[-1]))
            topo = None
            join_evidence = None
            same_road_lane = (
                a["source"].get("road_id") == b["source"].get("road_id")
                and a["source"].get("lane_id") == b["source"].get("lane_id")
            )
            if topology is not None:
                ep_a = a.get('_ends', [None, None])[1 if not ra else 0]
                ep_b = b.get('_ends', [None, None])[0 if not rb else 1]
                if ep_a is not None and ep_b is not None:
                    topo = topology.relation(ep_a, ep_b)
                if topo is not None:
                    join_evidence = 'xodr_topology'
                    allowed_max = max(max_gap, topology_max_gap_m)
                elif same_road_lane:
                    join_evidence = 'same_road_local'
                    allowed_max = max_gap
                elif gap <= geometric_fallback_max_gap_m:
                    join_evidence = 'small_gap_geometric'
                    allowed_max = geometric_fallback_max_gap_m
                else:
                    continue
                if gap > allowed_max:
                    continue
            else:
                if not min_gap < gap <= max_gap:
                    continue
                join_evidence = 'geometric_v3'
            if gap <= 1e-9:
                # XODR-linked roads/lanes often meet exactly at an endpoint.
                joined = np.vstack([pa, pb])
                if len(joined) < 2 or not LineString(joined).is_simple:
                    continue
                record = dict(
                    points=joined, cost=0.0, gap_m=0.0,
                    key_a=(ia, 1 if not ra else 0),
                    key_b=(ib, 0 if not rb else 1),
                    dot_a=1.0, dot_b=1.0, mutual_dot=1.0, lateral_m=0.0,
                    mark_type=type_a, mark_color=color_a,
                    reversed_a=ra, reversed_b=rb, topology=topo, join_evidence=join_evidence,
                )
                if best is None or (record["cost"], record["gap_m"]) < (best["cost"], best["gap_m"]):
                    best = record
                continue
            chord = (pb[0] - pa[-1]) / gap
            dot_a = float(ta @ chord)
            dot_b = float(tb @ chord)
            mutual = float(ta @ tb)
            lateral = max(abs(float(np.cross(ta, pb[0] - pa[-1]))),
                          abs(float(np.cross(tb, pb[0] - pa[-1]))))
            if dot_a < min_dot or dot_b < min_dot or mutual < 0.20 or lateral > max_lateral:
                continue
            bridge = LineString([tuple(pa[-1]), tuple(pb[0])])
            if _support(bridge, surface) < 0.90:
                continue
            if _third_line_blocked(bridge, lines, ia, ib):
                continue
            parts = np.asarray(bridge.coords, float)[1:-1] if len(bridge.coords) > 2 else np.empty((0, 2))
            joined = np.vstack([pa, parts, pb])
            if len(joined) < 2 or not LineString(joined).is_simple:
                continue
            cost = gap + 0.20 * (1.0 - min(dot_a, dot_b))
            record = dict(
                points=joined, cost=cost, gap_m=gap,
                key_a=(ia, 1 if not ra else 0),
                key_b=(ib, 0 if not rb else 1),
                dot_a=dot_a, dot_b=dot_b, mutual_dot=mutual, lateral_m=lateral,
                mark_type=type_a, mark_color=color_a,
                reversed_a=ra, reversed_b=rb, topology=topo, join_evidence=join_evidence,
            )
            if best is None or (record["cost"], record["gap_m"]) < (best["cost"], best["gap_m"]):
                best = record
    return best


def stitch_dividers(features: list[dict], surface=None, topology=None,
                    min_gap_m: float = 0.02, max_iterations: int = 200,
                    topology_max_gap_m: float = 25.0,
                    geometric_fallback_max_gap_m: float = 0.50):
    """Join same-paint endpoint pairs; topology mode uses XODR links only."""
    items = []
    for index, feature in enumerate(features):
        item = copy.deepcopy(feature)
        item["_index"] = index
        item["_ends"] = [
            _endpoint_meta(item["source"], 0, topology),
            _endpoint_meta(item["source"], 1, topology),
        ]
        items.append(item)
    joins = []
    rejected = []
    for _ in range(max_iterations):
        options = []
        lines = [LineString(np.asarray(item["points"], float)[:, :2]) for item in items]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                limits = _limits(items[i]["source"].get("mark_type", ""))
                candidate = _candidate(items[i], items[j], lines, surface, limits, min_gap_m, i, j,
                                       topology, topology_max_gap_m, geometric_fallback_max_gap_m)
                if candidate is not None:
                    options.append(candidate)
        if not options:
            break
        # Preserve v3's high-confidence local/small-gap joins before the
        # many zero-cost topology links consume their endpoints.
        def priority(q):
            return 0 if q.get("join_evidence") in ("same_road_local", "small_gap_geometric") else 1
        options.sort(key=lambda q: (priority(q), q["cost"], q["key_a"], q["key_b"]))
        used = set()
        selected = None
        for q in options:
            if q["key_a"] in used or q["key_b"] in used:
                continue
            # A second near-equal option sharing an endpoint is ambiguous
            # only within the same evidence tier.
            ambiguous = any(
                other is not q and priority(other) == priority(q) and
                other["cost"] < q["cost"] + 0.20 and
                (other["key_a"] in (q["key_a"], q["key_b"]) or
                 other["key_b"] in (q["key_a"], q["key_b"]))
                for other in options
            )
            if ambiguous:
                rejected.append(dict(reason="ambiguous_endpoint_candidate",
                                     gap_m=q["gap_m"], mark_type=q["mark_type"]))
                continue
            selected = q
            break
        if selected is None:
            break
        i = selected["key_a"][0]
        j = selected["key_b"][0]
        a, b = items[i], items[j]
        source = copy.deepcopy(a["source"])
        refs_a = source.get("source_refs", [])
        refs_b = b["source"].get("source_refs", [])
        source["source_refs"] = refs_a + refs_b
        source["stitched"] = True
        source["stitch_rule"] = RULE
        source["stitch_gap_m"] = round(selected["gap_m"], 6)
        source["stitch_components"] = [
            {k: a["source"].get(k) for k in ("road_id", "lane_id", "mark_type", "mark_color", "s_start", "s_end")},
            {k: b["source"].get(k) for k in ("road_id", "lane_id", "mark_type", "mark_color", "s_start", "s_end")},
        ]
        source["stitch_topology"] = selected.get("topology")
        source["stitch_evidence"] = selected.get("join_evidence")
        merged = dict(source=source, points=selected["points"].tolist())
        merged["length_m"] = float(LineString(selected["points"]).length)
        merged["_index"] = min(i, j)
        a_ends = a.get("_ends", [None, None])
        b_ends = b.get("_ends", [None, None])
        merged["_ends"] = [
            a_ends[1] if selected["reversed_a"] else a_ends[0],
            b_ends[0] if selected["reversed_b"] else b_ends[1],
        ]
        items = [item for k, item in enumerate(items) if k not in (i, j)] + [merged]
        joins.append(dict(
            rule=RULE, gap_m=selected["gap_m"], mark_type=selected["mark_type"],
            mark_color=selected["mark_color"], cost=selected["cost"],
            dot_a=selected["dot_a"], dot_b=selected["dot_b"],
            mutual_dot=selected["mutual_dot"], lateral_m=selected["lateral_m"],
            source_a=source["stitch_components"][0],
            source_b=source["stitch_components"][1],
            topology=selected.get("topology"),
            join_evidence=selected.get("join_evidence"),
        ))
    # Strip internal index keys.
    result = []
    for item in items:
        item.pop("_index", None)
        item.pop("_ends", None)
        result.append(item)
    evidence_counts = {}
    for item in joins:
        key = item.get('join_evidence') or 'unknown'
        evidence_counts[key] = evidence_counts.get(key, 0) + 1
    report = dict(
        rule=RULE,
        input_vectors=len(features),
        output_vectors=len(result),
        joins=len(joins),
        joins_by_evidence=evidence_counts,
        rejected_ambiguous=len(rejected),
        join_details=joins,
        topology_enabled=topology is not None,
        parameters=dict(min_gap_m=min_gap_m, broken_max_gap_m=9.0,
                        solid_max_gap_m=2.0, min_support_fraction=0.90,
                        third_line_buffer_m=0.08, topology_max_gap_m=topology_max_gap_m,
                        geometric_fallback_max_gap_m=geometric_fallback_max_gap_m),
    )
    return result, report
