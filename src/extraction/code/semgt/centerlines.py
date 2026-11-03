"""Optional prepared or generated centerlines, expressed in frame-local coordinates."""
import numpy as np
from shapely.geometry import LineString,box
from .geometry import transform,parts
from .bev import bounds

def local(world,row,roi):
    result=[];area=box(*bounds(roi))
    for f in world['features']:
        line=LineString(transform(f['points_xyz'],row['transform']))
        for i,part in enumerate(parts(line.intersection(area))):
            if part.length<=.05:continue
            xyz=np.asarray(part.coords).tolist();result.append(dict(id=f['id']+'/clip/'+str(i),parent_id=f['id'],
                render_points=[p[:2] for p in xyz],render_xyz=xyz,source=dict(f['source']),human_approved=False))
    return result


def validate_world(world,expected_sha):
    if world.get('schema')!='lanegt_centerline_world_v2' or world.get('generator')!='legacy_xodr_lane_geometry_v1' or world.get('xodr_sha256')!=expected_sha:raise ValueError('需要原版XODR处理链生成的v2中心线文件；旧CARLA采样缓存不可复用，请重新生成')
    if not world.get('audit',{}).get('passed'):raise ValueError('中心线世界文件缺少原版去重/拓扑校验通过记录')
    seen=set()
    if not isinstance(world.get('features'),list) or not world['features']:raise ValueError('中心线世界文件为空')
    for f in world['features']:
        if not isinstance(f.get('id'),str) or not f['id'] or f['id'] in seen:raise ValueError('中心线ID缺失或重复')
        seen.add(f['id']);p=np.asarray(f['points_xyz'],float)
        if p.ndim!=2 or p.shape[1]!=3 or len(p)<2 or not np.isfinite(p).all() or np.max(abs(p[:,2]))>1e-6:raise ValueError('中心线必须为有限平面XYZ曲线')
        if not isinstance(f.get('source'),dict) or f['source'].get('travel_s') not in ['increasing','decreasing']:raise ValueError('中心线方向来源缺失')
    return world


def clip_provided(features,roi):
    import copy
    area=box(*bounds(roi));result=[]
    for f in features:
        line=LineString(f['render_xyz']);cut=line.intersection(area)
        if cut.equals(line):result.append(copy.deepcopy(f));continue
        for i,part in enumerate(parts(cut)):
            if part.length<=.05:continue
            q=copy.deepcopy(f);xyz=np.asarray(part.coords).tolist()
            q.update(id=f['id']+':roi'+str(i),render_xyz=xyz,render_points=[p[:2] for p in xyz],points=None,
                source=dict(kind='clipped_provided_centerline',original_source=f['source']))
            result.append(q)
    return result
