"""从 XODR 模型提取带真实线型/颜色的车道线段。

与"用几何形态推断线型"的做法不同，本模块的 type/color 直接来自
OpenDRIVE <roadMark>，不做事后猜测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .xodr import (
    NON_PAINTED_MARK_TYPES,
    PAINTED_MARK_TYPES,
    Boundary,
    Road,
    XodrMap,
    mark_segments,
    road_boundaries,
)

# MapTRv2 目标类别（按本项目 2026-09-28 审计定义）
CLS_DIVIDER = "divider"
CLS_BOUNDARY = "boundary"
CLS_PED_CROSSING = "ped_crossing"

# 构成"可行驶道路面"的 lane 类型。sidewalk/median/none 不属于可行驶面。
DRIVABLE_LANE_TYPES = frozenset({"driving", "shoulder", "biking", "parking", "bidirectional"})
# 仅这些类型视为机动车行驶车道（用于判断某条边界是不是区域内部的分隔线）
TRAVEL_LANE_TYPES = frozenset({"driving", "bidirectional"})


@dataclass
class LaneLineSegment:
    """一条连续 s 区间上的车道线（或道路边界线）几何及其源属性。"""
    road_id: int
    lane_id: int            # 拥有该边界标线的车道
    side: str               # center | left | right
    lane_type: str          # 拥有者车道类型
    mark_type: str          # OpenDRIVE roadMark type
    mark_color: str
    lane_change: str
    mark_width: float | None
    s_start: float
    s_end: float
    junction: int
    points: np.ndarray = field(repr=False)   # (N, 3) CARLA 世界系 x, y, z

    @property
    def is_painted(self) -> bool:
        return self.mark_type in PAINTED_MARK_TYPES

    @property
    def length(self) -> float:
        if len(self.points) < 2:
            return 0.0
        d = np.diff(self.points[:, :2], axis=0)
        return float(np.hypot(d[:, 0], d[:, 1]).sum())

    @property
    def is_arrow_or_symbol(self) -> bool:
        return self.mark_type not in PAINTED_MARK_TYPES and \
            self.mark_type not in NON_PAINTED_MARK_TYPES


def _sample_s(s0: float, s1: float, step: float) -> np.ndarray:
    n = max(2, int(math.ceil((s1 - s0) / step)) + 1)
    return np.linspace(s0, s1, n)


def extract_road_segments(road: Road, xmap: XodrMap, step: float = 0.5,
                          include_unpainted: bool = False,
                          boundaries: list[Boundary] | None = None
                          ) -> list[LaneLineSegment]:
    """提取一条 road 上所有车道的边界线段（未跨 road 合并）。"""
    out: list[LaneLineSegment] = []
    bl = boundaries if boundaries is not None else road_boundaries(road)
    for b in bl:
        for s0, s1, mk in mark_segments(b, road):
            if not include_unpainted and mk.type in NON_PAINTED_MARK_TYPES:
                continue
            s = _sample_s(s0, s1, step)
            pts2 = b.xy(road, s, carla_frame=True)
            pts = np.concatenate([pts2, np.zeros((len(pts2), 1))], axis=1)
            out.append(LaneLineSegment(
                road_id=road.id, lane_id=b.lane_id, side=b.side,
                lane_type=b.lane_type, mark_type=mk.type, mark_color=mk.color,
                lane_change=mk.lane_change, mark_width=mk.width,
                s_start=s0, s_end=s1, junction=road.junction, points=pts,
            ))
    return out


def extract_all_segments(xmap: XodrMap, step: float = 0.5,
                         include_unpainted: bool = False,
                         exclude_junctions: bool = False
                         ) -> list[LaneLineSegment]:
    """全图提取。"""
    out: list[LaneLineSegment] = []
    for road in xmap.roads:
        if exclude_junctions and road.junction >= 0:
            continue
        out.extend(extract_road_segments(road, xmap, step=step,
                                         include_unpainted=include_unpainted))
    return out


# ------------------------------------------------------------ 分类

def drivable_span(lanes: list, side: str) -> tuple[int, int] | None:
    """同侧车道中构成可行驶面的 lane id 区间（含端点）。

    返回 (最内侧 lane id, 最外侧 lane id)；若该侧无可行驶车道返回 None。
    """
    ids = [l.id for l in lanes if l.type in DRIVABLE_LANE_TYPES]
    if not ids:
        return None
    return (min(ids, key=abs), max(ids, key=abs))


def classify(seg: LaneLineSegment, lanes_by_road: dict[int, list],
             drivable_types: frozenset[str] = DRIVABLE_LANE_TYPES
             ) -> str | None:
    return classify_ex(seg, lanes_by_road, drivable_types)[0]


def classify_ex(seg: LaneLineSegment, lanes_by_road: dict[int, list],
                drivable_types: frozenset[str] = DRIVABLE_LANE_TYPES
                ) -> tuple[str | None, str]:
    """按审计定义把线段归入 MapTRv2 类别；不满足条件返回 None。

    返回 (类别, 原因)。原因用于审计被丢弃的线段，避免"看不见的丢标"。

    boundary : 可行驶道路面（含 shoulder/非机动车道）的几何**外轮廓**。
               它是几何量而非"画出来的线"，故不要求该处有 roadMark 涂装
               —— Town10HD 的可行驶面外缘正好落在无涂装的 curb 上。
    divider  : 可行驶道路面**内部**的车道分隔结构，且该处确有涂装。
    其余（人行道边界、无涂装的内部车道界）不产出。

    ped_crossing 由 CARLA Map.get_crosswalks() 单独提供，此处不产出。
    """
    lanes = lanes_by_road.get(seg.road_id, [])
    this = next((l for l in lanes if l.id == seg.lane_id), None)
    if this is None:
        return None, "owning_lane_not_found"

    # 路口内部道路(junction >= 0)是交叉口的连接组织，不是 MapTRv2 意义上的
    # "道路"。其 single-side 车道结构会让 <center> 边界退化成穿过路口的扇形
    # 曲线——那是转向连接路径，不是道路外轮廓，故一律不产出 boundary。
    # 其实测确有的涂装标线（沿路延伸的虚线/边线）仍可作 divider。
    if seg.junction >= 0:
        if seg.is_painted:
            return CLS_DIVIDER, "junction_painted"
        return None, "junction_unpainted"

    if this.id == 0:
        # <center> 车道的 type 恒为 none，但其 roadMark 是中心线，不能按
        # "拥有者车道须可行驶" 过滤，否则整条黄线会丢失（本模块早期版本即如此）。
        has_left = any(l.id > 0 and l.type in drivable_types for l in lanes)
        has_right = any(l.id < 0 and l.type in drivable_types for l in lanes)
        if has_left and has_right:
            # 双向道路: 中心线位于可行驶面内部
            return ((CLS_DIVIDER, "centerline_bidirectional") if seg.is_painted
                    else (None, "centerline_unpainted"))
        if has_left or has_right:
            # 单向道路: 参考线处就是该侧道路面边缘
            return CLS_BOUNDARY, "centerline_oneway_edge"
        return None, "no_drivable_lane_on_either_side"

    if this.type not in drivable_types:
        # 拥有者车道本身不可行驶（人行道 / none / median）: 其边界不属于道路面
        return None, f"owning_lane_type_{this.type}"

    same_side = [l for l in lanes if (l.id > 0) == (this.id > 0) and l.id != 0]
    if not same_side:
        return None, "no_lane_on_side"
    span = drivable_span(same_side, seg.side)
    if span is None:
        return None, "no_drivable_lane_on_side"
    _inner_id, outer_id = span

    if abs(this.id) == abs(outer_id):
        return CLS_BOUNDARY, "surface_outer_edge"
    if seg.is_painted:
        return CLS_DIVIDER, "interior_painted"
    return None, f"interior_unpainted_{seg.mark_type}"


def annotate_classes(segments: list[LaneLineSegment], xmap: XodrMap,
                     drivable_types: frozenset[str] = DRIVABLE_LANE_TYPES
                     ) -> None:
    """就地写入 seg.cls 字段。"""
    lanes_by_road: dict[int, list] = {}
    for road in xmap.roads:
        for sec in road.sections:
            lanes_by_road.setdefault(road.id, []).extend(sec.lanes)
    for seg in segments:
        cls, reason = classify_ex(seg, lanes_by_road, drivable_types)
        seg.cls = cls  # type: ignore[attr-defined]
        seg.cls_reason = reason  # type: ignore[attr-defined]
