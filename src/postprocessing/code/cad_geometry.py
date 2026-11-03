"""Atomic CAD geometry replacement, preserving unchanged 3D and centerline exactly."""
import copy, math


def near(a,b,tol=1e-7): return len(a)==len(b) and all(abs(x-y)<=tol for x,y in zip(a,b))


def same_geometry(a,b):
    if len(a)!=len(b): return False
    if all(near(p,q) for p,q in zip(a,b)) or all(near(p,q) for p,q in zip(a,reversed(b))): return True
    if len(a)>3 and near(a[0],a[-1]) and near(b[0],b[-1]):
        aa=a[:-1];bb=b[:-1]
        for sequence in [bb,list(reversed(bb))]:
            for i,p in enumerate(sequence):
                if near(aa[0],p) and all(near(q,sequence[(i+j)%len(sequence)]) for j,q in enumerate(aa)): return True
    return False


def replace_geometry(targets,op,prior_ids,ground_z,bev_range=None):
    from edit_model import checked_bounds
    a,b,c,d=checked_bounds(bev_range)
    if op.get('expected_operation_ids')!=prior_ids: raise ValueError('CAD导出后的编辑历史不匹配')
    context=op.get('cad_context',{})
    if context.get('units')!='m' or not isinstance(context.get('session_id'),str): raise ValueError('CAD坐标元数据无效')
    if context.get('BEV_range_m',[a,b,c,d])!=[a,b,c,d]:raise ValueError('CAD范围与源GT不一致')
    features=op.get('features')
    if not isinstance(features,list) or len(features)>10000: raise ValueError('CAD实例列表无效')
    if sum(len(f.get('points',[])) for f in features if isinstance(f,dict))>100000: raise ValueError('CAD几何点数超限')
    lookup={f['id']:f for f in targets};keep=set();new=[]
    for index,f in enumerate(features):
        if not isinstance(f,dict) or f.get('class_name') not in ['divider','boundary','ped_crossing']: raise ValueError('CAD类别无效')
        ps=f.get('points')
        if not isinstance(ps,list) or len(ps)<2: raise ValueError('CAD点数不足')
        for p in ps:
            if not isinstance(p,list) or len(p)!=2 or any(type(v) not in [int,float] or not math.isfinite(v) for v in p): raise ValueError('CAD坐标必须是有限二维数值')
            if not (a<=p[0]<=c and b<=p[1]<=d): raise ValueError('CAD几何超出当前BEV范围')
        if sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(ps,ps[1:]))<.01: raise ValueError('CAD线条过短')
        source=f.get('source_target_id');original=lookup.get(source)
        if source is not None and (not original or original['class_name']!=f['class_name']): raise ValueError('CAD来源实例或类别不匹配')
        if original and same_geometry(original['full'],ps):
            if source in keep: raise ValueError('CAD出现重复的原始实例')
            keep.add(source);continue
        if f['class_name']=='ped_crossing':
            at_edge=lambda p: min(abs(p[0]-a),abs(p[0]-c),abs(p[1]-b),abs(p[1]-d))<1e-7
            clipped=original is not None and not near(original['full'][0],original['full'][-1]) and at_edge(ps[0]) and at_edge(ps[-1])
            if not clipped:
                if len(ps)<4 or not near(ps[0],ps[-1]): raise ValueError('斑马线必须为闭合轮廓（原有ROI裁剪轮廓除外）')
                area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ps,ps[1:])))/2
                if area<.001: raise ValueError('斑马线轮廓面积不足')
        identity='manual:'+op['id']+':cad'+str(index)
        xyz=[list(p)+[ground_z(p,targets)] for p in ps]
        if near(ps[0],ps[-1]): xyz[-1]=xyz[0][:]
        new.append(dict(id=identity,parent_id=identity,class_name=f['class_name'],full=[p[:2] for p in xyz],full_xyz=xyz,
            source=dict(kind='human_postprocess',operation_id=op['id'],operation_kind='cad_replace',
                source_target_ids=[source] if source else [],cad_session_id=context['session_id'],
                entity_handle=str(f.get('entity_handle','')),height_source='nearest_existing_3D_segment')))
    return [copy.deepcopy(t) for t in targets if t['class_name']=='centerline' or t['id'] in keep]+new
