"""复用原版车道条带结构与多边形构造。"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from shapely.geometry import Polygon
from .xodr import Boundary,Road

@dataclass
class Strip:
    """一条 road 某一侧的一段连续可行驶面。"""
    road_id: int
    side: str
    lane_ids: list[int]        # 从内到外的车道 id
    polygon: Polygon           # CARLA 世界系 (x, y)


def _strip_polygon(road: Road, inner: Boundary, outer: Boundary,
                   n: int) -> Polygon | None:
    """由内外两条边界在整条 road 上围成的条带多边形。"""
    s = np.linspace(0.0, road.length, n)
    p_out = outer.xy(road, s, carla_frame=True)
    p_in = inner.xy(road, s, carla_frame=True)
    ring = np.concatenate([p_out, p_in[::-1]], axis=0)
    if len(ring) < 4:
        return None
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area <= 0:
        return None
    return poly
