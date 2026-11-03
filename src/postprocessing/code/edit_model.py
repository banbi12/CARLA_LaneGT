"""Deterministic frame-local manual operations; no simulator or sampler imports."""
import copy, math, re

CLASSES = ['divider', 'ped_crossing', 'boundary', 'centerline']


def targets_from_gt(gt, order):
    lookup = {}
    for cls, entries in gt['classes'].items():
        for f in entries:
            lookup[f['id']] = dict(id=f['id'], parent_id=f['parent_id'], class_name=cls,
                full=copy.deepcopy(f['render_points']), full_xyz=copy.deepcopy(f['render_xyz']), source=copy.deepcopy(f['source']))
    if len(order) != len(lookup) or set(order) != set(lookup): raise ValueError('Target order/GT mismatch')
    return [lookup[i] for i in order]


def checked_bounds(value=None):
    b=[-15,-30,15,30] if value is None else value
    if not isinstance(b,list) or len(b)!=4 or any(type(v) not in [int,float] or not math.isfinite(v) for v in b) or b[0]>=b[2] or b[1]>=b[3]:raise ValueError('无效BEV范围')
    return b


def checked_xy(p,bev_range=None):
    if not isinstance(p, list) or len(p) != 2 or any(type(v) not in [int, float] or not math.isfinite(v) for v in p):
        raise ValueError('点坐标必须是两个有限数值')
    a,b,c,d=checked_bounds(bev_range)
    if not (a <= p[0] <= c and b <= p[1] <= d): raise ValueError('补线超出当前BEV范围')
    return list(p)


def ground_z(p, targets):
    best, z = float('inf'), 0.
    for f in targets:
        for a, b in zip(f['full_xyz'], f['full_xyz'][1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]; n = dx*dx+dy*dy
            t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/n)) if n else 0.
            d = (p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2
            if d < best: best, z = d, a[2]+t*(b[2]-a[2])
    return z


def replay(base, operations,bev_range=None):
    bev_range=checked_bounds(bev_range)
    targets = copy.deepcopy(base); seen = set()
    if not isinstance(operations, list) or len(operations) > 2000: raise ValueError('操作列表无效或过长')
    for operation_index,op in enumerate(operations):
        if not isinstance(op, dict) or not isinstance(op.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', op['id']) or op['id'] in seen:
            raise ValueError('操作ID无效或重复')
        seen.add(op['id']); kind = op.get('kind'); lookup = {f['id']: f for f in targets}
        new_id = 'manual:' + op['id']
        if new_id in lookup: raise ValueError('人工实例ID冲突')
        if kind == 'cad_replace':
            from cad_geometry import replace_geometry
            targets=replace_geometry(targets,op,[o['id'] for o in operations[:operation_index]],ground_z,bev_range)
            continue
        if kind == 'delete':
            f = lookup.get(op.get('target_id'))
            if not f or f['class_name'] == 'centerline': raise ValueError('无法删除该实例（centerline保持只读）')
            targets = [t for t in targets if t['id'] != f['id']]; continue
        source_ids = []
        if kind == 'add':
            cls = op.get('class_name')
            if cls not in ['divider', 'boundary']: raise ValueError('新增线段仅支持divider/boundary')
            ps = op.get('points')
            if not isinstance(ps, list) or len(ps) != 2: raise ValueError('请提供两个点')
            ps = [checked_xy(p,bev_range) for p in ps]
            if math.hypot(ps[0][0]-ps[1][0], ps[0][1]-ps[1][1]) < .01: raise ValueError('线段长度应至少为0.01米')
            xyz = [p+[ground_z(p, targets)] for p in ps]
        elif kind == 'connect':
            endpoints = [op.get('a'), op.get('b')]
            if any(not isinstance(e, dict) or e.get('end') not in ['start', 'end'] or e.get('target_id') not in lookup for e in endpoints):
                raise ValueError('连接端点无效，实例可能已被删除或合并')
            a, b = [lookup[e['target_id']] for e in endpoints]; cls = a['class_name']
            if cls not in ['divider', 'boundary'] or b['class_name'] != cls: raise ValueError('只允许连接同类divider或boundary')
            if any(f['full'][0] == f['full'][-1] for f in [a, b]): raise ValueError('闭合实例没有可连接的开放端点')
            source_ids = [a['id']] if a['id'] == b['id'] else [a['id'], b['id']]
            if a['id'] == b['id']:
                if endpoints[0]['end'] == endpoints[1]['end']: raise ValueError('请选择不同的端点')
                xyz = copy.deepcopy(a['full_xyz']) + [copy.deepcopy(a['full_xyz'][0])]
            else:
                aa = copy.deepcopy(a['full_xyz']); bb = copy.deepcopy(b['full_xyz'])
                if endpoints[0]['end'] == 'start': aa.reverse()
                if endpoints[1]['end'] == 'end': bb.reverse()
                if aa[-1] == bb[0]: bb = bb[1:]
                xyz = aa + bb
            targets = [t for t in targets if t['id'] not in source_ids]
        else: raise ValueError('未知操作类型')
        targets.append(dict(id=new_id, parent_id=new_id, class_name=cls,
            full=[p[:2] for p in xyz], full_xyz=xyz,
            source=dict(kind='human_postprocess', operation_id=op['id'], operation_kind=kind,
                        source_target_ids=source_ids, height_source='existing_endpoints' if kind == 'connect' else 'nearest_existing_3D_segment')))
    return targets


def edited_gt(base, targets, operations, base_sha, sampled=None):
    gt = copy.deepcopy(base); old = {f['id']: f for v in base['classes'].values() for f in v}
    gt['classes'] = {k: [] for k in CLASSES}
    for i, f in enumerate(targets):
        entry = copy.deepcopy(old.get(f['id']))
        if entry is None:
            entry = dict(id=f['id'], parent_id=f['parent_id'], source=copy.deepcopy(f['source']),
                render_points=copy.deepcopy(f['full']), render_xyz=copy.deepcopy(f['full_xyz']), points=None, human_approved=False)
        if sampled is not None and f['class_name'] != 'centerline': entry['points'] = sampled['fixed20'][i].tolist()
        gt['classes'][f['class_name']].append(entry)
    gt.update(algorithm_version=base['algorithm_version']+'+manual_v1',
        counts={k: len(v) for k, v in gt['classes'].items()}, actual_sampler_applied=sampled is not None,
        capacity_passed=len(targets) <= 128, human_approved=False, approved_for_training=False,
        manual_postprocess=dict(schema='maptrv2_gt_edit_patch_v1', base_gt_sha256=base_sha,
            operations=copy.deepcopy(operations), review='pending', straight_two_point_bridges=True,
            cad_geometry_applied=any(o['kind']=='cad_replace' for o in operations)))
    import sys
    from pathlib import Path
    if not any((Path(p)/'semgt/portable.py').is_file() for p in sys.path if p):
        from workspace import settings
        sys.path.insert(0,settings(Path(__file__).resolve().parents[1])['extractor_code'])
    from semgt.portable import finalize
    return finalize(gt,sampled is not None)
