"""OpenDRIVE 解析与车道边界几何重建。

指定Town10HD/Opt地图的车道边界约定：
  每条 lane 的 <roadMark> 描述该车道**背向参考线一侧**边界的标线；
  <center> 车道 id=0 的 <roadMark> 即中心线。
  因此第 k 条左侧车道的边界横向位置 t = laneOffset + sum(width_1..width_k)，
  其标线属性直接取自该 lane 的 roadMark 记录，无需任何形态学推断。

坐标系: OpenDRIVE 右手系，s 沿参考线，t 向左为正，单位米、弧度。
CARLA 世界系为左手系 (x, y, z)，通过 odr_to_carla_xy 对 OpenDRIVE 世界 y 坐标取反。
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

EPS = 1e-12


def odr_to_carla_xy(pts: np.ndarray) -> np.ndarray:
    """OpenDRIVE 世界系 -> CARLA 世界系。

    指定Town10HD/Opt地图的坐标约定: 两者仅差 y 轴取反
    （CARLA/UE4 为左手系），x、z 相同，heading 取反。
    验证: road 1 的参考线及 lane ±1/±2 中心与 map.get_waypoint_xodr()
    的位置吻合到 1e-3 m。
    """
    out = np.array(pts, dtype=float, copy=True)
    out[..., 1] = -out[..., 1]
    return out


def odr_to_carla_heading(hdg: float) -> float:
    """OpenDRIVE 参考线 heading(rad) -> CARLA yaw(rad)。"""
    return -hdg

# 有实际路面涂装的 roadMark 类型。none = 无标线，curb = 物理路缘。
PAINTED_MARK_TYPES = frozenset(
    {"solid", "broken", "solid solid", "broken broken",
     "solid broken", "broken solid", "botts dots", "grass"}
)
NON_PAINTED_MARK_TYPES = frozenset({"none", "curb"})


def _f(el: ET.Element | None, key: str, default: float = 0.0) -> float:
    """读取 OpenDRIVE 属性的浮点值，缺失时返回 default。"""
    if el is None:
        return default
    v = el.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _poly3_at(rec: "Poly3Record", s_abs: float) -> float:
    """求 a + b*ds + c*ds^2 + d*ds^3，ds 相对该记录自身的 s。"""
    ds = s_abs - rec.s
    return rec.a + ds * (rec.b + ds * (rec.c + ds * rec.d))


def piecewise_at(records: list["Poly3Record"], s_abs: float,
                 default: float = 0.0) -> float:
    """分段记录的取值语义: 取 s 之前最后一条记录求值，**不是求和**。

    OpenDRIVE 的 width/roadMark/laneOffset 都是分段定义，同一时刻只有
    一条记录生效。累加会重复计数（本模块早期版本即因此把 road 12 的
    lane -2 边界算成 -12.0 m 而非 -6.0 m）。
    """
    if not records:
        return default
    rec = records[0]
    for r in records:
        if r.s <= s_abs + EPS:
            rec = r
        else:
            break
    return _poly3_at(rec, s_abs)


@dataclass(frozen=True)
class Poly3Record:
    """形如 <width>/<laneOffset>/<elevation> 的三次多项式记录。"""
    s: float
    a: float
    b: float = 0.0
    c: float = 0.0
    d: float = 0.0

    def at(self, s_abs: float) -> float:
        return _poly3_at(self, s_abs)


@dataclass(frozen=True)
class RoadMarkRecord:
    """一条 <roadMark>，描述所属车道外侧边界在 [s, s_end) 区间上的标线。"""
    s: float                 # 绝对 s (laneSection.s + sOffset)
    s_offset: float          # 原始 sOffset，相对 laneSection
    type: str
    color: str
    width: float | None
    lane_change: str
    weight: str
    material: str
    s_end: float = field(default=math.inf)  # 由所属 laneSection/road 结束时回填

    @property
    def is_painted(self) -> bool:
        return self.type in PAINTED_MARK_TYPES


@dataclass
class Lane:
    id: int
    type: str
    level: bool
    widths: list[Poly3Record] = field(default_factory=list)
    marks: list[RoadMarkRecord] = field(default_factory=list)

    def width_at(self, s_abs: float) -> float:
        """车道宽度（分段语义）。"""
        return max(0.0, piecewise_at(self.widths, s_abs))


@dataclass
class LaneSection:
    s: float
    lanes: list[Lane] = field(default_factory=list)

    def lane(self, lane_id: int) -> Lane | None:
        return next((l for l in self.lanes if l.id == lane_id), None)


@dataclass
class Geometry:
    """<planView> 中的一段参考线几何。"""
    s: float
    x: float
    y: float
    hdg: float
    length: float
    kind: str          # line | arc | spiral | poly3 | paramPoly3
    params: dict

    def point_local(self, ds: float) -> tuple[float, float, float]:
        """返回该几何段内 ds 处的局部 (u, v, 切向角增量)。"""
        k = self.kind
        if k == "line":
            return ds, 0.0, 0.0

        if k == "arc":
            curv = self.params["curvature"]
            if abs(curv) < EPS:
                return ds, 0.0, 0.0
            ang = curv * ds
            return math.sin(ang) / curv, (1.0 - math.cos(ang)) / curv, ang

        if k == "spiral":
            c0 = self.params["curvStart"]
            c1 = self.params["curvEnd"]
            L = max(self.length, EPS)
            n = max(8, int(abs(ds) * 4) + 8)
            xs = np.linspace(0.0, ds, n + 1)
            theta = c0 * xs + (c1 - c0) * xs * xs / (2.0 * L)
            u = np.trapz(np.cos(theta), xs)
            v = np.trapz(np.sin(theta), xs)
            return float(u), float(v), float(c0 * ds + (c1 - c0) * ds * ds / (2.0 * L))

        if k == "poly3":
            p = self.params
            u = ds
            v = p["a"] + p["b"] * u + p["c"] * u * u + p["d"] * u ** 3
            dv = p["b"] + 2.0 * p["c"] * u + 3.0 * p["d"] * u * u
            return u, v, math.atan(dv)

        if k == "paramPoly3":
            p = self.params
            prange = self.length if p.get("pRange") == "arcLength" else 1.0
            # 数值求弧长参数: 先粗采样 p，再按弧长反查
            n = 64
            ps = np.linspace(0.0, prange, n + 1)
            us = p["aU"] + p["bU"] * ps + p["cU"] * ps ** 2 + p["dU"] * ps ** 3
            vs = p["aV"] + p["bV"] * ps + p["cV"] * ps ** 2 + p["dV"] * ps ** 3
            seg = np.hypot(np.diff(us), np.diff(vs))
            arc = np.concatenate([[0.0], np.cumsum(seg)])
            u = float(np.interp(ds, arc, us))
            v = float(np.interp(ds, arc, vs))
            du = float(np.interp(ds, arc, np.gradient(us, arc, edge_order=1)))
            dv = float(np.interp(ds, arc, np.gradient(vs, arc, edge_order=1)))
            return u, v, math.atan2(dv, du)

        raise ValueError(f"未知的 planView 几何类型: {k}")


@dataclass
class RoadObject:
    """<object> 元素（如 crosswalk），轮廓以对象局部 (u, v) 给出。"""
    id: str
    type: str
    name: str
    s: float
    t: float
    hdg: float
    length: float
    width: float
    corners: list[tuple[float, float, float]] = field(default_factory=list)

    def outline_world(self, road: "Road", carla_frame: bool = True) -> np.ndarray:
        """对象轮廓 -> CARLA 世界系 (N, 3)。

        cornerLocal 的 (u, v) 位于对象自身坐标系: 原点在道路 (s, t) 处，
        u 轴沿对象航向、v 轴为其左法向；对象航向 = 道路参考线航向 + 对象 hdg。
        """
        x0, y0, road_hdg = road.ref_point(self.s)
        base_t = road.lane_offset_at(self.s) + self.t
        nx, ny = -math.sin(road_hdg), math.cos(road_hdg)
        ox = x0 + base_t * nx
        oy = y0 + base_t * ny

        th = road_hdg + self.hdg
        c, s_ = math.cos(th), math.sin(th)
        ux, uy = c, s_          # u 轴
        vx, vy = -s_, c         # v 轴（左法向）

        pts = np.array([[ox + u * ux + v * vx,
                         oy + u * uy + v * vy,
                         z] for u, v, z in self.corners], dtype=float)
        return odr_to_carla_xy(pts) if carla_frame else pts


@dataclass
class Road:
    id: int
    length: float
    junction: int
    geometries: list[Geometry] = field(default_factory=list)
    lane_offsets: list[Poly3Record] = field(default_factory=list)
    sections: list[LaneSection] = field(default_factory=list)
    objects: list[RoadObject] = field(default_factory=list)

    # ---- 参考线 ----
    def _geometry_at(self, s: float) -> tuple[Geometry, float]:
        s = min(max(s, 0.0), self.length)
        geo = self.geometries[0]
        for g in self.geometries:
            if g.s <= s + EPS:
                geo = g
            else:
                break
        return geo, s - geo.s

    def ref_point(self, s: float) -> tuple[float, float, float]:
        """参考线在世界系下的 (x, y, heading_rad)。"""
        geo, ds = self._geometry_at(s)
        u, v, dang = geo.point_local(ds)
        c, sn = math.cos(geo.hdg), math.sin(geo.hdg)
        x = geo.x + u * c - v * sn
        y = geo.y + u * sn + v * c
        return x, y, geo.hdg + dang

    def ref_xy(self, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """向量化的参考线求值，s 为一维数组。"""
        s = np.clip(np.asarray(s, dtype=float), 0.0, self.length)
        xs = np.empty_like(s)
        ys = np.empty_like(s)
        hs = np.empty_like(s)
        for i, si in enumerate(s):
            xs[i], ys[i], hs[i] = self.ref_point(float(si))
        return xs, ys, hs

    def lane_offset_at(self, s: float) -> float:
        return piecewise_at(self.lane_offsets, s)

    def section_at(self, s: float) -> LaneSection:
        sec = self.sections[0]
        for x in self.sections:
            if x.s <= s + EPS:
                sec = x
            else:
                break
        return sec


class XodrMap:
    """解析后的 OpenDRIVE 地图。"""

    def __init__(self, roads: list[Road], header: dict, source: str = ""):
        self.roads = roads
        self.by_id = {r.id: r for r in roads}
        self.header = header
        self.source = source

    @classmethod
    def from_text(cls, text: str, source: str = "") -> "XodrMap":
        root = ET.fromstring(text)
        hdr_el = root.find("header")
        header = dict(hdr_el.attrib) if hdr_el is not None else {}
        roads: list[Road] = []
        for r in root.findall("road"):
            road = Road(
                id=int(r.get("id")),
                length=float(r.get("length", "0")),
                junction=int(r.get("junction", "-1")),
                lane_offsets=[
                    Poly3Record(s=_f(lo, "s"), a=_f(lo, "a"), b=_f(lo, "b"),
                                c=_f(lo, "c"), d=_f(lo, "d"))
                    for lo in r.findall("lanes/laneOffset")
                ],
            )
            for g in r.findall("planView/geometry"):
                child = list(g)[0]
                kind = child.tag
                params = {k: (v if k == "pRange" else float(v))
                          for k, v in child.attrib.items()}
                road.geometries.append(Geometry(
                    s=_f(g, "s"), x=_f(g, "x"), y=_f(g, "y"),
                    hdg=_f(g, "hdg"), length=_f(g, "length"),
                    kind=kind, params=params,
                ))
            road.geometries.sort(key=lambda g: g.s)
            for obj_el in r.findall("objects/object"):
                corners = [
                    (_f(c, "u"), _f(c, "v"), _f(c, "z"))
                    for c in obj_el.findall("outline/cornerLocal")
                ]
                road.objects.append(RoadObject(
                    id=obj_el.get("id", ""),
                    type=obj_el.get("type", ""),
                    name=obj_el.get("name", ""),
                    s=_f(obj_el, "s"), t=_f(obj_el, "t"), hdg=_f(obj_el, "hdg"),
                    length=_f(obj_el, "length"), width=_f(obj_el, "width"),
                    corners=corners,
                ))
            for sec_el in r.findall("lanes/laneSection"):
                sec = LaneSection(s=_f(sec_el, "s"))
                for lane_el in sec_el.iter("lane"):
                    lane = Lane(
                        id=int(lane_el.get("id")),
                        type=lane_el.get("type", "none"),
                        level=lane_el.get("level", "false") == "true",
                        widths=[
                            Poly3Record(s=sec.s + _f(w, "sOffset"), a=_f(w, "a"),
                                        b=_f(w, "b"), c=_f(w, "c"), d=_f(w, "d"))
                            for w in lane_el.findall("width")
                        ],
                    )
                    lane.widths.sort(key=lambda x: x.s)
                    for mk in lane_el.findall("roadMark"):
                        lane.marks.append(RoadMarkRecord(
                            s=sec.s + _f(mk, "sOffset"),
                            s_offset=_f(mk, "sOffset"),
                            type=mk.get("type", "none"),
                            color=mk.get("color", "standard"),
                            width=(float(mk.get("width")) if mk.get("width") else None),
                            lane_change=mk.get("laneChange", "none"),
                            weight=mk.get("weight", "standard"),
                            material=mk.get("material", "standard"),
                        ))
                    sec.lanes.append(lane)
                sec.lanes.sort(key=lambda l: -l.id)  # 左外 -> 右外
                road.sections.append(sec)
            road.sections.sort(key=lambda s: s.s)
            roads.append(road)
        return cls(roads, header, source)

    @classmethod
    def from_file(cls, path: str | Path) -> "XodrMap":
        p = Path(path)
        return cls.from_text(p.read_text(), source=str(p))


# ---------------------------------------------------------------- 车道边界

@dataclass
class Boundary:
    """一条车道边界线，拥有确定的横向位置函数与标线记录。"""
    road_id: int
    lane_id: int                      # 拥有该边界标线的车道 id（0 表示中心线）
    side: str                         # center | left | right
    section_s: float
    lane_type: str                    # 拥有者车道类型
    marks: list[RoadMarkRecord]
    _widths: list[Poly3Record]        # 该边界外侧所有车道的宽度累加（分段序列）

    def t_at(self, road: Road, s: float) -> float:
        """边界相对参考线的横向坐标 t（左正右负）。

        _widths 是"外侧各车道宽度累加"的分段序列，按分段语义取值。
        """
        base = road.lane_offset_at(s)
        acc = max(0.0, piecewise_at(self._widths, s))
        if self.side == "left":
            return base + acc
        if self.side == "right":
            return base - acc
        return base

    def xy(self, road: Road, s: np.ndarray, carla_frame: bool = True) -> np.ndarray:
        """边界折线，返回 (N, 2)。carla_frame=True 时输出 CARLA 世界系。"""
        xs, ys, hs = road.ref_xy(s)
        t = np.array([self.t_at(road, float(si)) for si in s])
        # 左法向: heading 逆时针旋转 90°
        nx = -np.sin(hs)
        ny = np.cos(hs)
        pts = np.stack([xs + t * nx, ys + t * ny], axis=1)
        return odr_to_carla_xy(pts) if carla_frame else pts


def _cumulative_widths(lanes_sorted: list[Lane], upto_index: int) -> list[Poly3Record]:
    """把前 upto_index+1 条车道的宽度记录合并为一个按 s 生效的记录序列。

    宽度只在 s 上分段，且同侧各车道的 width 记录 s 值通常一致；
    这里做保守处理: 收集全部记录的 s 断点，逐段取各车道在该段的宽度记录。
    """
    out: list[Poly3Record] = []
    lanes = lanes_sorted[: upto_index + 1]
    breaks = sorted({r.s for l in lanes for r in l.widths})
    if not breaks:
        return out
    for b in breaks:
        a = b_ = c = d = 0.0
        for l in lanes:
            rec = None
            for r in l.widths:
                if r.s <= b + EPS:
                    rec = r
                else:
                    break
            if rec is None and l.widths:
                rec = l.widths[0]
            if rec is not None:
                # 记录起点对齐到 b，保持多项式形状
                shift = b - rec.s
                a += rec.a + rec.b * shift + rec.c * shift ** 2 + rec.d * shift ** 3
                b_ += rec.b + 2 * rec.c * shift + 3 * rec.d * shift ** 2
                c += rec.c + 3 * rec.d * shift
                d += rec.d
        out.append(Poly3Record(s=b, a=a, b=b_, c=c, d=d))
    return out


def road_boundaries(road: Road) -> list[Boundary]:
    """枚举一条 road 上的全部车道边界（含中心线）。"""
    out: list[Boundary] = []
    for sec in road.sections:
        left = sorted([l for l in sec.lanes if l.id > 0], key=lambda l: l.id)
        right = sorted([l for l in sec.lanes if l.id < 0], key=lambda l: -l.id)
        center = sec.lane(0)

        if center is not None:
            out.append(Boundary(
                road_id=road.id, lane_id=0, side="center", section_s=sec.s,
                lane_type=center.type, marks=list(center.marks),
                _widths=[],
            ))
        for i, lane in enumerate(left):
            out.append(Boundary(
                road_id=road.id, lane_id=lane.id, side="left", section_s=sec.s,
                lane_type=lane.type, marks=list(lane.marks),
                _widths=_cumulative_widths(left, i),
            ))
        for i, lane in enumerate(right):
            out.append(Boundary(
                road_id=road.id, lane_id=lane.id, side="right", section_s=sec.s,
                lane_type=lane.type, marks=list(lane.marks),
                _widths=_cumulative_widths(right, i),
            ))
    return out


def _same_mark_style(a: RoadMarkRecord, b: RoadMarkRecord) -> bool:
    """两条 roadMark 的可见属性是否一致（用于合并相邻碎片）。"""
    return (a.type == b.type and a.color == b.color
            and a.lane_change == b.lane_change and a.width == b.width
            and a.weight == b.weight)


def mark_segments(boundary: Boundary, road: Road,
                  merge: bool = True) -> list[tuple[float, float, RoadMarkRecord]]:
    """把边界的 roadMark 记录展开为 [s_start, s_end) 区间序列，按 s 排序。

    路口内部道路的 roadMark 常被写成属性相同、沿 s 紧邻的极小片段
    （本图实测有 0.0/0.1/0.2/0.5/1.4/... 这类切分）。merge=True 时合并
    这类相邻同属性片段，这是消除"碎片"问题的关键一步。
    """
    road_end = road.length
    recs = sorted(boundary.marks, key=lambda m: m.s)
    out: list[tuple[float, float, RoadMarkRecord]] = []
    for i, m in enumerate(recs):
        s0 = max(0.0, m.s)
        s1 = recs[i + 1].s if i + 1 < len(recs) else road_end
        s1 = min(s1, road_end)
        if s1 - s0 <= EPS:
            continue
        if (merge and out and _same_mark_style(out[-1][2], m)
                and abs(out[-1][1] - s0) <= 1e-6):
            out[-1] = (out[-1][0], s1, out[-1][2])
        else:
            out.append((s0, s1, m))
    return out
