"""Migrated original lane selection, partial-overlap deduplication and topology.

Function bodies are preserved from the archived centerline pipeline. The module
has no historical directory, fixed BEV, simulator or image-rendering dependency.
"""
import math
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union
from .legacy_xodr import XodrMap,road_boundaries

def parse_topology(xodr: Path):
    root = ET.parse(xodr).getroot()
    roads = {}
    for road in root.findall("road"):
        links = {e.tag: dict(e.attrib) for e in road.findall("link/*")}
        lanes = {}
        for sec in road.findall("lanes/laneSection"):
            ss = float(sec.get("s"))
            for lane in sec.findall("*/lane"):
                lanes[(ss, int(lane.get("id")))] = {
                    e.tag: int(e.get("id")) for e in lane.findall("link/*")}
        roads[int(road.get("id"))] = {"links": links, "lanes": lanes}
    junctions = []
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            for link in conn.findall("laneLink"):
                junctions.append({
                    "junction_id": int(junction.get("id")),
                    "connection_id": int(conn.get("id")),
                    "incoming_road": int(conn.get("incomingRoad")),
                    "connecting_road": int(conn.get("connectingRoad")),
                    "contact_point": conn.get("contactPoint"),
                    "from_lane": int(link.get("from")),
                    "to_lane": int(link.get("to")),
                })
    return roads, junctions

def selected_lanes(xmap, lane_decisions, step_m):
    overrides = {(x["road_id"], x["section_s"], x["lane_id"]): x
                 for x in lane_decisions["lane_inclusion_overrides"]}
    features, deferred, issues = [], [], []
    for road in xmap.roads:
        boundaries = {(b.section_s, b.lane_id): b for b in road_boundaries(road)}
        for i, section in enumerate(road.sections):
            s0 = section.s
            s1 = road.sections[i + 1].s if i + 1 < len(road.sections) else road.length
            for lane in section.lanes:
                if lane.id == 0:
                    continue
                decision = overrides.get((road.id, section.s, lane.id))
                chosen = lane.type == "driving"
                if not chosen:
                    if lane.type in ("shoulder", "parking", "biking", "none"):
                        deferred.append({"road_id": road.id, "section_s": section.s,
                                         "lane_id": lane.id, "lane_type": lane.type,
                                         "reason": (
                                             "reviewed_drivable_surface_no_route_link"
                                             if decision and decision["decision"] == "include_drivable_none"
                                             else "not_automatically_routeable")})
                    continue
                own = boundaries.get((section.s, lane.id))
                inner_id = 0 if abs(lane.id) == 1 else lane.id - (1 if lane.id > 0 else -1)
                inner = boundaries.get((section.s, inner_id))
                if own is None or inner is None or s1 - s0 < 0.05:
                    issues.append({"road_id": road.id, "lane_id": lane.id,
                                   "reason": "missing_boundary_or_short_section"})
                    continue
                ss = np.linspace(s0, s1, max(2, math.ceil((s1 - s0) / step_m) + 1))
                a, b = inner.xy(road, ss), own.xy(road, ss)
                widths = np.linalg.norm(a - b, axis=1)
                if float(np.max(widths)) < 0.1:
                    issues.append({"road_id": road.id, "lane_id": lane.id,
                                   "reason": "degenerate_width"})
                    continue
                pts = (a + b) / 2
                if lane.id > 0:
                    pts = pts[::-1]
                line = LineString(pts)
                source = {"road_id": road.id, "section_s": section.s,
                          "lane_id": lane.id, "lane_type": lane.type,
                          "junction_id": road.junction, "s_start": s0, "s_end": s1,
                          "travel_s": "decreasing" if lane.id > 0 else "increasing",
                          "selection": "driving",
                          "source_refs": [{"road_id": road.id, "section_s": section.s,
                                           "lane_id": lane.id}]}
                features.append({"id": f"{road.id}:{section.s:g}:{lane.id}",
                                 "source": source, "points": pts.tolist(),
                                 "length_m": round(line.length, 4),
                                 "width_min_m": round(float(np.min(widths)), 4)})
    return features, deferred, issues

def _line_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "LineString":
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _line_parts(part)

def deduplicate_centerlines(features):
    """Keep shared path geometry once while retaining the directed lane graph."""
    accepted = []
    suppressed = 0.0
    for feature in sorted(features, key=lambda f: (-f["length_m"], f["id"])):
        line = LineString(feature["points"])
        matches = []
        for item in accepted:
            owner = item["line"]
            if line.distance(owner) >= 0.015:
                continue
            shared = line.intersection(owner.buffer(0.05))
            if shared.length < min(0.2, 0.8 * min(line.length, owner.length)):
                continue
            at = shared.representative_point()
            def direction(path):
                pos = path.project(at)
                a = path.interpolate(max(0, pos - 0.1))
                b = path.interpolate(min(path.length, pos + 0.1))
                norm = math.hypot(b.x - a.x, b.y - a.y)
                return ((b.x - a.x) / norm, (b.y - a.y) / norm)
            u, v = direction(line), direction(owner)
            if abs(u[0] * v[0] + u[1] * v[1]) >= 0.94:
                matches.append(item)
        for item in matches:
            if feature["id"] not in item["source_ids"]:
                item["source_ids"].add(feature["id"])
                item["source_refs"].append({
                    "element_id": feature["id"],
                    "road_id": feature["source"]["road_id"],
                    "lane_id": feature["source"]["lane_id"],
                    "associated_length_m": round(item["line"].intersection(
                        line.buffer(0.05)).length, 4)})
        remaining = line.difference(unary_union([x["line"].buffer(0.05)
                                                  for x in matches])) if matches else line
        parts = list(_line_parts(remaining))
        suppressed += line.length - sum(p.length for p in parts)
        for part in parts:
            if part.length < 0.05:
                continue
            accepted.append({"line": part, "owner": feature,
                             "source_ids": {feature["id"]},
                             "source_refs": [{"element_id": feature["id"],
                                              "road_id": feature["source"]["road_id"],
                                              "lane_id": feature["source"]["lane_id"],
                                              "associated_length_m": round(part.length, 4)}]})
    represented = {sid for x in accepted for sid in x["source_ids"]}
    original = {f["id"] for f in features}
    if represented != original:
        raise ValueError(f"Lost centerline provenance: {original - represented}")
    output = []
    for index, item in enumerate(accepted):
        source = dict(item["owner"]["source"])
        source["source_refs"] = item["source_refs"]
        output.append({"id": f"centerline:{index}", "source": source,
                       "points": [list(p) for p in item["line"].coords],
                       "length_m": round(item["line"].length, 4)})
    report = {"raw_vectors": len(features), "output_vectors": len(output),
              "raw_length_m": round(sum(f["length_m"] for f in features), 4),
              "output_length_m": round(sum(f["length_m"] for f in output), 4),
              "removed_overlap_length_m": round(suppressed, 4),
              "source_ids": len(original), "represented_source_ids": len(represented),
              "distance_m": 0.015, "overlap_buffer_m": 0.05,
              "minimum_fragment_m": 0.05}
    return output, report

def build_edges(features, road_info, junction_links):
    by_lane = {(f["source"]["road_id"], f["source"]["lane_id"]): f for f in features}
    edges = []
    def add(kind, src, dst, detail):
        row = {"kind": kind, "from": src, "to": dst, **detail}
        start, end = by_lane.get(src), by_lane.get(dst)
        if start is None or end is None:
            missing = src if start is None else dst
            exists_in_xodr = any(lane_id == missing[1] for _, lane_id in
                                 road_info.get(missing[0], {}).get("lanes", {}))
            row.update(status="excluded" if exists_in_xodr else "rejected",
                       reason=("lane_not_selected_as_routeable" if exists_in_xodr
                               else "lane_missing_in_xodr"))
        else:
            gap = math.dist(start["points"][-1], end["points"][0])
            row["gap_m"] = round(gap, 5)
            if gap > 0.5:
                row.update(status="review", reason="endpoint_gap_gt_0.5m")
            else:
                row.update(status="accepted", reason="source_topology_and_endpoint_agree")
        edges.append(row)

    for f in features:
        src = (f["source"]["road_id"], f["source"]["lane_id"])
        road = road_info[src[0]]
        direction = "successor" if src[1] < 0 else "predecessor"
        rlink = road["links"].get(direction)
        lane_link = road["lanes"].get((f["source"]["section_s"], src[1]), {}).get(direction)
        if rlink is None or rlink.get("elementType") != "road":
            continue
        if lane_link is None:
            edges.append({"kind": "road_link", "from": src,
                          "road_link": rlink, "status": "review",
                          "reason": "missing_lane_link"})
            continue
        dst = (int(rlink["elementId"]), lane_link)
        add("road_link", src, dst, {"road_contact_point": rlink.get("contactPoint")})

    for link in junction_links:
        src = (link["incoming_road"], link["from_lane"])
        dst = (link["connecting_road"], link["to_lane"])
        row_detail = {k: v for k, v in link.items() if k not in (
            "incoming_road", "connecting_road", "from_lane", "to_lane")}
        if dst in by_lane:
            expected = "start" if dst[1] < 0 else "end"
            if link["contact_point"] != expected:
                edges.append({"kind": "junction_laneLink", "from": src,
                              "to": dst, **row_detail, "status": "review",
                              "reason": "contact_point_opposes_travel_direction"})
                continue
        add("junction_laneLink", src, dst, row_detail)
    return edges
