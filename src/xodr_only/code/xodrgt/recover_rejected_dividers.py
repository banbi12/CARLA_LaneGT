#!/usr/bin/env python3
"""Recover XODR divider segments rejected by the whole-line 80% surface rule.

The original XODR-only selector drops a divider if less than 80% of its length
lies inside the eroded drivable surface. At junctions that removes real painted
lines. V3 clips such lines to the surface instead, keeping only the valid parts.
"""
from __future__ import annotations

import copy
from typing import Iterable

from shapely.geometry import LineString

RULE = "xodr_rejected_divider_surface_clip_v1"


def _line_parts(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    return [part for part in getattr(geom, "geoms", []) if part.geom_type == "LineString"]


def recover_rejected(rejected: Iterable[dict], surface, margin_m: float = 0.01,
                     min_length_m: float = 0.50):
    """Clip rejected divider lines to the drivable surface and retain valid parts."""
    rejected = list(rejected)
    inner = surface.buffer(-margin_m) if surface is not None and not surface.is_empty else None
    recovered = []
    dropped = []
    for item in rejected:
        source = copy.deepcopy(item["source"])
        line = LineString(item["points"])
        geom = line if inner is None else line.intersection(inner)
        parts = _line_parts(geom)
        kept = 0
        for index, part in enumerate(parts):
            if part.length < min_length_m:
                continue
            points = [list(p) for p in part.coords]
            src = copy.deepcopy(source)
            src["recovered_from_rejected"] = True
            src["recovery_rule"] = RULE
            src["original_interior_fraction"] = source.get("interior_fraction")
            src["recovery_surface_margin_m"] = margin_m
            src["recovered_length_m"] = round(float(part.length), 6)
            src["recovered_part_index"] = index
            recovered.append(dict(source=src, points=points, length_m=float(part.length)))
            kept += 1
        if kept == 0:
            dropped.append({
                "source": source,
                "length_m": round(float(line.length), 6),
                "reason": "no_surface_part_above_minimum",
            })
    report = {
        "rule": RULE,
        "input_rejected": len(rejected),
        "recovered_vectors": len(recovered),
        "recovered_length_m": round(sum(x["length_m"] for x in recovered), 4),
        "dropped_rejected": len(dropped),
        "parameters": {"surface_margin_m": margin_m, "minimum_part_m": min_length_m},
        "dropped": dropped,
    }
    return recovered, report
