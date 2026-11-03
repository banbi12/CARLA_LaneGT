"""Observation-derived double-yellow midlines and smooth dash continuation."""
import copy
import numpy as np
from shapely.geometry import LineString,Point
from shapely.ops import unary_union,substring
from .geometry import sample,tangent,bridge,project,uid,parts
from .connection_guard import unsafe_fragment,endpoint_provenance,straight_extension

def runs(mask):
    cuts=np.flatnonzero(np.diff(np.r_[False,mask,False].astype(int)))
    return list(zip(cuts[::2],cuts[1::2]))

def clear_side_corridor(line,meta,labels,depth,policy):
    if labels is None or depth is None:return 0.
    ss,xy=sample(line,.2);vectors=np.asarray([tangent(line,float(s)) for s in ss]);normals=np.c_[-vectors[:,1],vectors[:,0]]
    points=np.vstack([xy+normals*offset for offset in [-.65,-.5,-.3,-.15,.15,.3,.5,.65]])
    uv=np.rint(project(np.c_[points,np.zeros(len(points))],meta)).astype(int);h,w=labels.shape
    inside=(uv[:,0]>=0)&(uv[:,0]<w)&(uv[:,1]>=0)&(uv[:,1]<h);valid=np.zeros(len(uv),bool)
    p=uv[inside];rays=np.c_[p,np.ones(len(p))]@np.linalg.inv(np.asarray(meta['intrinsic'])).T;t=np.asarray(meta['optical_to_world_carla'])
    z=((rays*depth[p[:,1],p[:,0],None])@t[:3,:3].T+t[:3,3])[:,2]
    valid[inside]=np.isin(labels[p[:,1],p[:,0]],[1,24])&np.isfinite(z)&(z>policy['ground_min_z'])&(z<policy['ground_max_z'])
    return float(valid.mean())

def double_yellow(features,meta,policy,labels=None,depth=None):
    out=[copy.deepcopy(f) for f in features if not (f['class_name']=='divider' and f['mark_color']=='yellow')]
    yellow=[f for f in features if f['class_name']=='divider' and f['mark_color']=='yellow']
    lines=[LineString(np.asarray(f['points_xyz'])[:,:2]) for f in yellow];candidates=[]
    for i,la in enumerate(lines):
        ss,pa=sample(la);ta=np.asarray([tangent(la,float(s)) for s in ss])
        for j in range(i+1,len(lines)):
            lb=lines[j];sb=np.asarray([lb.project(Point(p)) for p in pa]);pb=np.asarray([lb.interpolate(float(s)).coords[0] for s in sb]);distance=np.linalg.norm(pa-pb,axis=1)
            tb=np.asarray([tangent(lb,float(s)) for s in sb]);speed=np.abs(np.gradient(sb,ss))
            align=np.abs((ta*tb).sum(axis=1))
            corridor=(distance>=policy['double_min_spacing_m'])&(distance<=policy['double_max_spacing_m'])
            valid=corridor&(align>.95)&(speed>.05)&(speed<1.8)
            # Nearest projections can pause at a rasterized rail corner. Reconcile
            # only short intervals with continuous observed parallel-track support.
            for lo,hi in runs(~valid):
                if lo>0 and hi<len(valid) and ss[hi]-ss[lo-1]<=.4 and np.all(corridor[lo:hi]&(align[lo:hi]>.9)):
                    valid[lo:hi]=True
            for lo,hi in runs(valid):
                length=ss[hi-1]-ss[lo]
                if hi-lo<5 or length<policy['double_min_overlap_m']:
                    continue
                widths=distance[lo:hi]
                if np.percentile(widths,95)-np.percentile(widths,5)>policy['double_max_width_variation_m']:
                    continue
                mid=(pa[lo:hi]+pb[lo:hi])/2
                if not LineString(mid).is_simple:
                    continue
                candidates.append(dict(i=i,j=j,pa=pa[lo:hi],pb=pb[lo:hi],mid=mid,length=float(length),width=float(np.median(widths))))
    rejected=set();audit=[]
    for n,a in enumerate(candidates):
        for m,b in enumerate(candidates):
            if n==m or not ({a['i'],a['j']}&{b['i'],b['j']}):
                continue
            # Compare common rail coverage, not road/lane identifiers.
            common=next(iter({a['i'],a['j']}&{b['i'],b['j']}))
            ap=a['pa'] if common==a['i'] else a['pb'];bp=b['pa'] if common==b['i'] else b['pb']
            overlap=LineString(ap).intersection(LineString(bp).buffer(.08)).length
            if overlap<.5*min(a['length'],b['length']):
                continue
            if b['width']<a['width']-.05:
                rejected.add(n)
            elif abs(b['width']-a['width'])<.08:
                rejected.add(n)
    coverage=[[] for _ in yellow]
    for n,item in enumerate(candidates):
        if n in rejected:
            audit.append(dict(action='yellow_pair_pending_nonunique_or_not_mutual_nearest',source_ids=[yellow[item['i']]['id'],yellow[item['j']]['id']]))
            continue
        i,j=item['i'],item['j'];xy=item['mid'];xyz=np.c_[xy,np.zeros(len(xy))];identifier=uid(xyz,'double_midline')
        out.append(dict(id=identifier,logical_parent_id=identifier,class_name='divider',points_xyz=xyz.tolist(),uv=project(xyz,meta).tolist(),source='observed_double_yellow_midcurve',review='pending',mark_type='solid solid',mark_color='yellow',dash_eligible=False,
                        raw_paint_sources=[yellow[i]['id'],yellow[j]['id']],paired_tracks_xy=[item['pa'].tolist(),item['pb'].tolist()],observed_segments_xyz=[],connections=[],pair_width_m=item['width']))
        coverage[i].append(LineString(item['pa']));coverage[j].append(LineString(item['pb']))
        audit.append(dict(action='double_yellow_two_observed_tracks_to_one_midcurve',source_ids=[yellow[i]['id'],yellow[j]['id']],id=identifier,length_m=item['length'],median_width_m=item['width'],old_map_used=False))
    for i,f in enumerate(yellow):
        nearby=any(i!=j and lines[i].distance(other)<=policy['double_max_spacing_m'] for j,other in enumerate(lines))
        visibility=clear_side_corridor(lines[i],meta,labels,depth,policy)
        if not coverage[i] and not nearby and visibility>=.95:
            single=copy.deepcopy(f);single['source']='observed_single_yellow_with_clear_adjacent_ground';out.append(single)
            audit.append(dict(action='single_yellow_observed_no_parallel_track',source_id=f['id'],side_corridor_observed_fraction=visibility,old_map_used=False));continue
        remaining=lines[i].difference(unary_union(coverage[i]).buffer(.04)) if coverage[i] else lines[i]
        for part in parts(remaining):
            if part.length<.05:
                continue
            p=np.asarray(part.coords);xyz=np.c_[p,np.zeros(len(p))];q=copy.deepcopy(f)
            q.update(id=uid(xyz,'yellow_pending'),class_name='unresolved',points_xyz=xyz.tolist(),uv=project(xyz,meta).tolist(),source='unpaired_or_ambiguous_yellow_observation_pending',original_observation_id=f['id']);out.append(q)
    return out,audit

def bridge_supported(curve,meta,labels,depth,stripes,policy):
    uv=np.rint(project(np.c_[curve,np.zeros(len(curve))],meta)).astype(int);h,w=labels.shape;b=int(policy['border_px'])
    if np.any((uv[:,0]<b)|(uv[:,0]>=w-b)|(uv[:,1]<b)|(uv[:,1]>=h-b)):
        return False,'reference_border'
    x,y=uv[:,0],uv[:,1]
    if np.any(stripes[y,x]):
        return False,'observed_crosswalk_paint'
    rays=np.c_[uv,np.ones(len(uv))]@np.linalg.inv(np.asarray(meta['intrinsic'])).T;t=np.asarray(meta['optical_to_world_carla'])
    z=((rays*depth[y,x,None])@t[:3,:3].T+t[:3,3])[:,2]
    valid=np.isin(labels[y,x],[1,24])&np.isfinite(z)&(z>policy['ground_min_z'])&(z<policy['ground_max_z'])
    arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(curve,axis=0),axis=1))]
    bad=max([float(arc[min(hi,len(arc)-1)]-arc[max(0,lo-1)]) for lo,hi in runs(~valid)]+[0.])
    if valid.mean()<policy['dash_min_road_fraction'] or bad>policy['dash_max_unknown_length_m']:
        return False,'insufficient_observed_road_corridor'
    return True,'observed_road_corridor'

def endpoint_trace_fragment(fragment,a,b,pa,pb,curve,policy):
    """Exempt only a local, proven continuation fragment; preserve third marks."""
    if fragment.get('class_name')!='unresolved' or fragment.get('source')!='short_observed_stroke_pending':return False
    points=np.asarray(fragment['points_xyz'])[:,:2];line=LineString(points)
    if line.length>policy['endpoint_fragment_max_length_m']:return False
    traces=set(fragment.get('source_trace_ids',[]))
    for parent,end in [(a,pa[-1]),(b,pb[0])]:
        distance=np.linalg.norm(points-end,axis=1)
        if distance.min()>policy['endpoint_fragment_contact_m'] or distance.max()>policy['endpoint_fragment_extent_m']:continue
        if traces.intersection(parent.get('source_trace_ids',[])):return True
        component=fragment.get('component')
        related=component is not None and component in parent.get('source_components',[parent.get('component')])
        if not related:continue
        if fragment.get('evidence',{}).get('median_width_m',float('inf'))>policy['maximum_thin_width_m']:continue
        bridge_line=LineString(curve);vector=points[-1]-points[0];vector/=max(np.linalg.norm(vector),1e-12)
        s=bridge_line.project(line.interpolate(line.length/2));alignment=abs(vector@tangent(bridge_line,s))
        if alignment>.96 and all(bridge_line.distance(Point(p))<=.1 for p in points):return True
    return False

def connect_dashes(features,meta,labels,depth,stripes,policy,connection_reference=None):
    out=copy.deepcopy(features);audit=[];pending=[]
    guarded=policy['connection_guards_enabled']
    if guarded and policy['connection_use_xodr'] and connection_reference is not None:connection_reference.validate_map(meta)
    def can_extend(f):
        lengths=f.get('observed_run_lengths_m',[])
        return bool(lengths) and max(lengths)<=policy['dash_extension_max_observed_run_m']
    def repeated_support(f,gap):
        intervals=[q['gap_m'] for q in f.get('connections',[]) if q.get('kind')=='observed_dash_continuation_C1']
        if f.get('mark_type')!='broken' or len(intervals)<2:return False
        reference=float(np.median(intervals))
        return abs(gap-reference)<=.25+reference*policy['dash_extension_gap_relative_tolerance']
    for iteration in range(200):
        options=[]
        for i,a in enumerate(out):
            if a['class_name']!='divider' or not (a.get('dash_eligible') or can_extend(a)):
                continue
            for j in range(i+1,len(out)):
                b=out[j]
                if b['class_name']!='divider' or not (b.get('dash_eligible') or can_extend(b)) or a['mark_color']!=b['mark_color']:
                    continue
                for ra in [False,True]:
                    pa=np.asarray(a['points_xyz'])[::(-1 if ra else 1),:2]
                    for rb in [False,True]:
                        pb=np.asarray(b['points_xyz'])[::(-1 if rb else 1),:2];gap=float(np.linalg.norm(pb[0]-pa[-1]))
                        maximum=policy['dash_straight_max_gap_m'] if guarded else policy['dash_max_gap_m']
                        if not policy['dash_min_gap_m']<gap<=maximum:
                            continue
                        curve,ta,tb=bridge(pa,pb);chord=(pb[0]-pa[-1])/gap
                        if min(ta@chord,tb@chord)<policy['dash_min_tangent_chord_dot'] or ta@tb<policy['dash_min_mutual_dot']:
                            continue
                        unsafe_ends=unsafe_fragment(a,0 if ra else -1) or unsafe_fragment(b,-1 if rb else 0)
                        fragment_straight_repeat_exception=False
                        if guarded and unsafe_ends and gap>=policy['dash_fragment_guard_min_gap_m']:
                            # A real clipped dash may touch a stop-bar component.
                            # Retain its ordinary-range connection only after a
                            # repeated straight track has formed from other paint.
                            supported,_=straight_extension(a,b,pa,pb,ta,tb,gap,policy)
                            fragment_straight_repeat_exception=supported and gap<=policy['dash_max_gap_m']
                            if not fragment_straight_repeat_exception:
                                pending.append(dict(source_ids=[a['id'],b['id']],reason='untrusted_clipped_or_branch_fragment',gap_m=gap));continue
                        long_straight=False;straight_evidence=None
                        if gap>policy['dash_max_gap_m']:
                            long_straight,straight_evidence=straight_extension(a,b,pa,pb,ta,tb,gap,policy,unsafe_ends)
                            if not long_straight:
                                pending.append(dict(source_ids=[a['id'],b['id']],reason='long_gap_without_strong_straight_evidence',gap_m=gap));continue
                        extended=not a.get('dash_eligible') or not b.get('dash_eligible') or any(max(f.get('observed_run_lengths_m',[0]))>policy['dash_max_observed_run_m'] for f in [a,b])
                        if extended:
                            if not can_extend(a) or not can_extend(b):continue
                            if min(ta@chord,tb@chord)<policy['dash_extension_tangent_dot']:continue
                            if not (repeated_support(a,gap) or repeated_support(b,gap) or long_straight):continue
                        line=LineString(curve)
                        if not line.is_simple or line.length>gap*policy['dash_max_curve_chord_ratio']:
                            continue
                        supported,reason=bridge_supported(curve,meta,labels,depth,stripes,policy)
                        if not supported:
                            pending.append(dict(source_ids=[a['id'],b['id']],reason=reason,gap_m=gap));continue
                        core=substring(line,min(.12,line.length*.1),max(line.length-.12,line.length*.9))
                        blocked=False;exemptions=[]
                        for k,q in enumerate(out):
                            if k in (i,j):continue
                            other=LineString(np.asarray(q['points_xyz'])[:,:2])
                            if core.intersects(other) or core.buffer(.1).intersection(other).length>.4:
                                if endpoint_trace_fragment(q,a,b,pa,pb,curve,policy):
                                    exemptions.append(q['id']);continue
                                blocked=True;break
                        if blocked:
                            pending.append(dict(source_ids=[a['id'],b['id']],reason='third_observed_line_or_marking',gap_m=gap,blocking_id=q['id']));continue
                        map_assessment=dict(decision='neutral',reason='connection_reference_not_supplied')
                        if guarded and policy['connection_use_xodr'] and connection_reference is not None:
                            map_assessment=connection_reference.assess(a,b,pa,pb,curve,ta,tb,policy)
                            if map_assessment['decision']=='conflict':
                                pending.append(dict(source_ids=[a['id'],b['id']],reason=map_assessment['reason'],gap_m=gap,xodr_evidence=map_assessment));continue
                        joined=np.vstack([pa,curve[1:-1],pb])
                        if not LineString(joined).is_simple:
                            continue
                        turn=abs(float(np.arctan2(np.cross(ta,tb),ta@tb)))
                        options.append(dict(i=i,j=j,ra=ra,rb=rb,curve=curve,joined=joined,gap=gap,cost=gap+.2*turn,endpoint_fragment_exemptions=exemptions,observed_repeat_supported_extension=extended,
                            conditional_straight_extension=long_straight,straight_evidence=straight_evidence,xodr_evidence=map_assessment,
                            fragment_straight_repeat_exception=fragment_straight_repeat_exception))
        if not options:
            break
        endpoints={}
        for q in options:
            for key in [(q['i'],0 if q['ra'] else -1),(q['j'],-1 if q['rb'] else 0)]:endpoints.setdefault(key,[]).append(q)
        selected=None
        for q in sorted(options,key=lambda q:(q['cost'],out[q['i']]['id'],out[q['j']]['id'])):
            unique=True
            for key in [(q['i'],0 if q['ra'] else -1),(q['j'],-1 if q['rb'] else 0)]:
                qq=sorted(endpoints[key],key=lambda item:item['cost'])
                if qq[0] is not q or (len(qq)>1 and qq[1]['cost']-q['cost']<.2 and qq[1]['gap']<q['gap']*1.2):
                    unique=False;break
            if unique:selected=q;break
        if selected is None:
            pending.append(dict(reason='ambiguous_dash_endpoint_candidates'));break
        q=selected;a=out[q['i']];b=out[q['j']];xyz=np.c_[q['joined'],np.zeros(len(q['joined']))]
        record=dict(kind='observed_dash_continuation_C1',source_ids=sorted(a.get('source_ids',[a['id']])+b.get('source_ids',[b['id']])),gap_m=q['gap'],points_xy=q['curve'].tolist(),old_road_lane_ids_used=False,mutual_unique_endpoints=True,endpoint_fragment_exemptions=q['endpoint_fragment_exemptions'])
        record['observed_repeat_supported_extension']=q['observed_repeat_supported_extension']
        record.update(conditional_straight_extension=q['conditional_straight_extension'],straight_evidence=q['straight_evidence'],xodr_evidence=q['xodr_evidence'])
        record['fragment_straight_repeat_exception']=q['fragment_straight_repeat_exception']
        ends=[copy.deepcopy(endpoint_provenance(a,-1 if q['ra'] else 0)),copy.deepcopy(endpoint_provenance(b,0 if q['rb'] else -1))]
        a['source_trace_ids']=sorted(set(a.get('source_trace_ids',[])+b.get('source_trace_ids',[])))
        a['source_components']=sorted(set(a.get('source_components',[a.get('component')])+b.get('source_components',[b.get('component')]))-{None})
        a.update(id=uid(xyz,'logical_dash'),points_xyz=xyz.tolist(),uv=project(xyz,meta).tolist(),source='logical_observed_dash_curve',mark_type='broken',dash_eligible=True,source_ids=record['source_ids'],observed_run_lengths_m=a['observed_run_lengths_m']+b['observed_run_lengths_m'],observed_segments_xyz=a['observed_segments_xyz']+b['observed_segments_xyz'],connections=a['connections']+b['connections']+[record],endpoint_provenance=ends);out.pop(q['j']);audit.append(record)
    return out,audit,pending
