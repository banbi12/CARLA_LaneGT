"""Remove repeated XODR roadMark geometry while retaining branch tails and source IDs."""
from __future__ import annotations

import math

from shapely.geometry import LineString
from shapely.ops import unary_union


def _parts(geom):
    if geom.is_empty:
        return
    if geom.geom_type == "LineString":
        yield geom
    elif hasattr(geom, "geoms"):
        for part in geom.geoms:
            yield from _parts(part)


def _tangent(line: LineString, position: float) -> tuple[float, float]:
    before = line.interpolate(max(0.0, position - 0.1))
    after = line.interpolate(min(line.length, position + 0.1))
    dx, dy = after.x - before.x, after.y - before.y
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _key(source: dict) -> tuple:
    return (source["road_id"], source["lane_id"], source["mark_type"],
            source["mark_color"], round(source["s_start"], 5),
            round(source["s_end"], 5))


def _reference(source: dict, overlap_m: float) -> dict:
    return {"road_id": source["road_id"], "lane_id": source["lane_id"],
            "junction": source["junction"], "mark_type": source["mark_type"],
            "mark_color": source["mark_color"],
            "s_start": source["s_start"], "s_end": source["s_end"],
            "associated_length_m": round(overlap_m, 4)}


def _is_same_paint(candidate: LineString, accepted: LineString,
                   candidate_source: dict, accepted_source: dict,
                   distance_m: float, overlap_buffer_m: float) -> bool:
    if (candidate_source["mark_type"], candidate_source["mark_color"]) != (
            accepted_source["mark_type"], accepted_source["mark_color"]):
        return False
    if candidate.distance(accepted) >= distance_m:
        return False
    nearby = candidate.intersection(accepted.buffer(overlap_buffer_m))
    if nearby.length < min(0.2, 0.8 * min(candidate.length, accepted.length)):
        return False
    point = nearby.representative_point()
    a = _tangent(candidate, candidate.project(point))
    b = _tangent(accepted, accepted.project(point))
    return abs(a[0] * b[0] + a[1] * b[1]) >= 0.94


def deduplicate_dividers(features: list[dict], *, distance_m: float = 0.015,
                         overlap_buffer_m: float = 0.03,
                         min_fragment_m: float = 0.05) -> tuple[list[dict], dict]:
    """Keep one geometric copy of each painted interval; do not join branches.

    The longest input owns a shared interval. Later inputs contribute only their
    uncovered tails, while every matched source is recorded on the owner.
    """
    indexed = list(enumerate(features))
    indexed.sort(key=lambda pair: (-LineString(pair[1]["points"]).length,
                                   _key(pair[1]["source"]), pair[0]))
    accepted: list[dict] = []
    audit = []
    discarded_short_m = 0.0
    for original_index, feature in indexed:
        line = LineString(feature["points"])
        source = feature["source"]
        matches = [item for item in accepted if _is_same_paint(
            line, item["line"], source, item["source"],
            distance_m, overlap_buffer_m)]
        for item in matches:
            shared = item["line"].intersection(line.buffer(overlap_buffer_m)).length
            if _key(source) not in item["source_keys"]:
                item["source_refs"].append(_reference(source, shared))
                item["source_keys"].add(_key(source))
        remainder = (line.difference(unary_union(
            [item["line"].buffer(overlap_buffer_m) for item in matches]))
            if matches else line)
        fragments = list(_parts(remainder))
        kept = [part for part in fragments if part.length >= min_fragment_m]
        discarded_short_m += sum(part.length for part in fragments
                                 if part.length < min_fragment_m)
        for part in kept:
            accepted.append({
                "line": part, "source": source,
                "source_refs": [_reference(source, part.length)],
                "source_keys": {_key(source)},
            })
        audit.append({
            "input_index": original_index,
            "source": source,
            "input_length_m": round(line.length, 4),
            "matched_existing_vectors": len(matches),
            "output_fragments": len(kept),
            "retained_length_m": round(sum(part.length for part in kept), 4),
            "removed_as_overlap_m": round(line.length - sum(
                part.length for part in fragments), 4),
        })

    result = []
    for item in accepted:
        owner = dict(item["source"])
        owner["source_refs"] = item["source_refs"]
        result.append({
            "source": owner,
            "points": [list(point) for point in item["line"].coords],
            "length_m": round(item["line"].length, 4),
        })
    all_keys = {_key(feature["source"]) for feature in features}
    represented_keys = {key for item in accepted for key in item["source_keys"]}
    if all_keys != represented_keys:
        raise ValueError("Divider source provenance was lost during deduplication")
    report = {
        "input_vectors": len(features),
        "output_vectors": len(result),
        "input_length_m": round(sum(LineString(f["points"]).length
                                    for f in features), 4),
        "output_length_m": round(sum(item["line"].length
                                     for item in accepted), 4),
        "inputs_with_overlap": sum(row["matched_existing_vectors"] > 0
                                   for row in audit),
        "fully_suppressed_inputs": sum(row["output_fragments"] == 0 for row in audit),
        "discarded_short_fragment_length_m": round(discarded_short_m, 4),
        "source_key_count": len(all_keys),
        "represented_source_key_count": len(represented_keys),
        "matching_parameters": {
            "minimum_distance_m": distance_m,
            "overlap_buffer_m": overlap_buffer_m,
            "minimum_kept_fragment_m": min_fragment_m,
            "minimum_parallel_cosine": 0.94,
        },
        "input_audit": sorted(audit, key=lambda row: row["input_index"]),
    }
    return result, report
