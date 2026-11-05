"""将复用的旧版几何函数装配为独立、可审计的世界缓存。"""
from pathlib import Path
import numpy as np
from mapgt.common import digest
from mapgt.world import flat_map_guard,checked_feature
from semgt.io import load,sha
from semgt.legacy_xodr import XodrMap
from semgt.legacy_centerline_pipeline import generate as centerlines
from . import VERSION

SCHEMA='lanegt_xodr_world_v1'

def decisions(path,expected):
    if path is None:return {}
    value=load(path)
    if value.get('xodr_sha256')!=expected:raise ValueError('人工决定文件与 XODR 指纹不一致')
    return value

def generate(repository,xodr,lane_decisions=None,boundary_decisions=None):
    # Import only in the separate Shapely 2 geometry process.
    from .legacy_map import (build_strips,make_surface,annotation_boundaries,
                             precision_audit,selected_dividers)
    from .crosswalks import crosswalks_from_xodr
    from .deduplicate_dividers import deduplicate_dividers
    from .stitch_dividers import stitch_dividers
    from .xodr_topology import XodrTopology
    from .recover_rejected_dividers import recover_rejected
    repository=Path(repository);expected=load(repository/'config/resources.town10.json')['files']['capture/server_Town10HD.xodr']
    if sha(xodr)!=expected:raise ValueError('仅支持指纹匹配的 Town10HD XODR')
    plane=flat_map_guard(xodr);xmap=XodrMap.from_file(xodr)
    lane=decisions(lane_decisions,expected);boundary=decisions(boundary_decisions,expected)
    shoulder={(d['road_id'],d['section_s'],d['lane_id']):d for d in lane.get('shoulder_overrides',[])}
    overrides={(d['road_id'],d['section_s'],d['lane_id']):d for d in lane.get('lane_inclusion_overrides',[])}
    strips,shoulders=build_strips(xmap,1.5,.5,shoulder,overrides)
    crossing_arrays=crosswalks_from_xodr(xmap)
    surface,parts,rings,holes=make_surface(strips,.005,crossing_arrays,5.,lane.get('hole_fill_overrides',[]))
    boundaries,excluded=annotation_boundaries(rings,boundary)
    selected,rejected=selected_dividers(xmap,surface,.05)
    recovered,recovery=recover_rejected(rejected,surface)
    raw=selected+recovered
    dividers,dedup=deduplicate_dividers(raw)
    topology=XodrTopology.from_file(xodr)
    dividers,stitch=stitch_dividers(dividers,surface,topology=topology)
    crossings=[dict(source=dict(xodr_index=i,road_id=r.id,object_id=o.id),points=o.outline_world(r)[:,:2].tolist())
               for i,(r,o) in enumerate((r,o) for r in xmap.roads for o in r.objects if o.type=='crosswalk' and len(o.corners)>=3)]
    features=[]
    for cls,entries in [('divider',dividers),('boundary',boundaries),('ped_crossing',crossings)]:
        for entry in entries:
            identifier=cls+':'+digest(dict(source=entry['source'],geometry=entry['points']))[:24]
            f=dict(id=identifier,class_name=cls,points_xyz=[[float(p[0]),float(p[1]),0.] for p in entry['points']],source=entry['source'])
            checked_feature(dict(f,**{'class':cls}));features.append(f)
    centers=centerlines(xodr,.5)
    cache=dict(schema=SCHEMA,generator=VERSION,xodr_sha256=expected,plane=plane,features=features,
        centerlines=centers,legacy_world=dict(map='Town10HD_Opt',xodr_sha256=expected,
            dividers=dividers,raw_dividers=raw,rejected_dividers=rejected,
            recovered_dividers=recovered,divider_recovery_report=recovery,
            boundary_rings=rings,boundary_lines=boundaries,
            crosswalks=crossings,divider_dedup_report=dedup,
            divider_stitch_report=stitch,xodr_topology=topology.describe(),
            surface_parts=len(parts),surface_area_m2=float(surface.area),hole_decisions=holes,
            excluded_boundary_segments=excluded,shoulder_decisions=shoulders,
            precision_checks=precision_audit(strips,.005)),
        parameters=dict(shoulder_min_width_m=1.5,surface_step_m=.5,surface_grid_m=.005,
            divider_interior_margin_m=.05,fill_unconnected_hole_max_area_m2=5.,deduplicate_dividers=True,
            stitch_dividers=True,divider_stitch_max_gap_m=9.0,topology_stitch=True,topology_max_gap_m=25.0,geometric_fallback_max_gap_m=0.50,
            recover_rejected_dividers=True,recovery_surface_margin_m=0.01,recovery_min_part_m=0.50),
        decision_files={name:dict(sha256=sha(p),applied=True) if p else dict(applied=False)
                        for name,p in [('lane_decisions',lane_decisions),('boundary_decisions',boundary_decisions)]},
        semantic_images_used=False,RGB_used_for_geometry=False,depth_used=False,GPU_used=False,CARLA_started=False,
        provenance=load(repository/'config/xodr_only/provenance.json'),candidate_only=True,human_approved=False)
    validate(cache,expected)
    return cache

def validate(world,expected):
    if world.get('schema')!=SCHEMA or world.get('generator')!=VERSION or world.get('xodr_sha256')!=expected:
        raise ValueError('需要匹配地图与版本的 XODR-only 世界缓存')
    seen=set();classes=set()
    for f in world.get('features',[]):
        checked_feature(dict(f,**{'class':f['class_name']}))
        if f['class_name'] not in ['divider','boundary','ped_crossing'] or f['id'] in seen:raise ValueError('XODR-only 类别或实例 ID 无效')
        seen.add(f['id']);classes.add(f['class_name'])
    if classes!={'divider','boundary','ped_crossing'}:raise ValueError('XODR-only 世界缓存缺少类别')
    if not world.get('centerlines',{}).get('audit',{}).get('passed'):raise ValueError('中心线原版校验记录缺失')
    centers=world['centerlines'].get('features',[])
    if not centers:raise ValueError('世界缓存缺少中心线几何')
    for f in centers:
        checked_feature(dict(f,**{'class':'centerline'}))
        if f['id'] in seen:raise ValueError('中心线 ID 与其他几何重复')
        seen.add(f['id'])
    if world['legacy_world']['divider_dedup_report']['source_key_count']!=world['legacy_world']['divider_dedup_report']['represented_source_key_count']:
        raise ValueError('旧版 divider 去重来源丢失')
    recovery=world['legacy_world'].get('divider_recovery_report')
    if not recovery or recovery.get('rule')!='xodr_rejected_divider_surface_clip_v1':
        raise ValueError('XODR-only 世界缓存缺少 rejected divider 恢复记录')
    stitch=world['legacy_world'].get('divider_stitch_report')
    if not stitch or stitch.get('rule')!='xodr_same_paint_endpoint_stitch_v1':
        raise ValueError('XODR-only 世界缓存缺少 divider 连接记录')
    if not world['legacy_world'].get('xodr_topology'):
        raise ValueError('XODR-only 世界缓存缺少 XODR 拓扑记录')
    return world
