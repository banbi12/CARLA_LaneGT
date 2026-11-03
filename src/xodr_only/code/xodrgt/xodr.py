"""复用已迁入的原版 XODR 解析器，避免维护两份解析代码。"""
from semgt.legacy_xodr import (NON_PAINTED_MARK_TYPES,PAINTED_MARK_TYPES,Boundary,Road,XodrMap,mark_segments,road_boundaries)
