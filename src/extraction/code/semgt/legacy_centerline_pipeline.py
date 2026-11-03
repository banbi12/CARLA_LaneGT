"""Original XODR lane-center and shared-geometry pipeline, without legacy IO."""
from collections import Counter
import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union
from mapgt.common import digest
from .legacy_xodr import XodrMap
from .legacy_centerlines import selected_lanes,parse_topology,deduplicate_centerlines,build_edges
ENGINE='legacy_xodr_lane_geometry_v1'

def generate(xodr,step):
    xmap=XodrMap.from_file(xodr)
    raw,deferred,issues=selected_lanes(xmap,{'lane_inclusion_overrides':[]},step)
    # mapgt.world.geometries historically deduplicated raw world nodes named lane:...
    for f in raw:f['id']='lane:'+f['id']
    centers,stats=deduplicate_centerlines(raw)
    roads,links=parse_topology(xodr);edges=build_edges(raw,roads,links)
    check=audit(raw,centers,edges)
    features=[]
    for f in centers:
        points=[[float(x),float(y),0.] for x,y in f['points']]
        features.append(dict(id='center_geometry:'+digest(dict(source=f['source'],points=f['points']))[:24],
            points_xyz=points,source=f['source']))
    return dict(features=features,raw_centerlines=raw,deduplication=stats,
        topology=dict(nodes=[dict(id=f['id'],source=f['source']) for f in raw],edges=edges),
        audit=check,deferred_lanes=deferred,geometry_issues=issues)

def audit(raw,centers,edges):
    if not raw or not centers:raise ValueError('原版中心线流程未生成几何')
    ids={f['id'] for f in raw};represented={ref['element_id'] for f in centers for ref in f['source']['source_refs']}
    if ids!=represented:raise ValueError('中心线去重后来源不完整')
    lines=[LineString(f['points']) for f in centers]
    for line in lines:
        if not line.is_valid or not np.isfinite(np.asarray(line.coords)).all() or line.length<.05:raise ValueError('无效中心线几何')
    covered=unary_union([line.buffer(.06) for line in lines])
    missing=max(LineString(f['points']).difference(covered).length for f in raw)
    duplicates=[]
    for i,line in enumerate(lines):
        for j in range(i):
            shared=line.intersection(lines[j].buffer(.05)).length
            if shared>=min(.5,.8*min(line.length,lines[j].length)):duplicates.append([i,j,float(shared)])
    accepted=[e for e in edges if e['status']=='accepted']
    indegree=Counter(tuple(e['to']) for e in accepted);outdegree=Counter(tuple(e['from']) for e in accepted)
    orphans=[f['id'] for f in raw if f['source']['junction_id']>=0 and (not indegree[(f['source']['road_id'],f['source']['lane_id'])] or not outdegree[(f['source']['road_id'],f['source']['lane_id'])])]
    gap=max([e.get('gap_m',0.) for e in accepted]+[0.])
    result=dict(passed=missing<=.001 and not duplicates and not orphans and gap<=.5,
        raw_source_ids=len(ids),represented_source_ids=len(represented),maximum_raw_missing_length_at_006m=float(missing),
        duplicate_pairs_at_005m=duplicates,junction_orphans=orphans,accepted_topology_max_gap_m=float(gap),
        topology_status_counts=dict(Counter(e['status'] for e in edges)))
    if not result['passed']:raise ValueError('原版中心线来源/覆盖/拓扑校验失败: '+str(result))
    return result
