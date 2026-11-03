"""复用原版 XODR 横道对象轮廓。"""
from __future__ import annotations
import numpy as np
from .xodr import XodrMap

def crosswalks_from_xodr(xmap: XodrMap) -> list[np.ndarray]:
    """从 XODR 的 <object type="crosswalk"> 取横道轮廓（CARLA 世界系）。

    2026-09-28 实测: 本图 16 个横道与 Map.get_crosswalks() 逐点吻合，
    Hausdorff 距离中位数 6e-6 m、最大 1.3e-5 m。故真值提取可完全
    脱离 CARLA 服务端，只需 .xodr 文件。
    """
    out: list[np.ndarray] = []
    for road in xmap.roads:
        for obj in road.objects:
            if obj.type == "crosswalk" and len(obj.corners) >= 3:
                out.append(obj.outline_world(road, carla_frame=True))
    return out
