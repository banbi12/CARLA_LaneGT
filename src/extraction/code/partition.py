"""Derived world boundary partitions; original geometry is never modified."""
import math
import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union
from mapgt.common import require,digest


def arc(points):
    p=np.asarray(points,dtype=float)
    require(p.ndim==2 and p.shape[1]==3 and len(p)>1 and np.isfinite(p).all(),'PARTITION_XYZ')
    s=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(p[:,:2],axis=0),axis=1))]
    require(s[-1]>0,'PARTITION_ZERO_LENGTH')
    return p,s


def at(p,s,values):
    return np.column_stack([np.interp(np.asarray(values),s,p[:,k]) for k in range(3)])


def subline(points,start,end):
    p,s=arc(points)
    require(-1e-8<=start<end<=s[-1]+1e-8,'PARTITION_INTERVAL')
    inside=p[(s>start+1e-10)&(s<end-1e-10)]
    result=np.vstack((at(p,s,[start]),inside,at(p,s,[end])))
    return result[np.r_[True,np.linalg.norm(np.diff(result,axis=0),axis=1)>1e-12]]


def policy(name,max_length=None):
    value=dict(version='boundary_partition_trial_v1',name=name,feature_split=name!='baseline',
        max_length_m=max_length,sample_step_m=.25,tangent_window_m=2.,turn_threshold_deg=25.,
        helper_simplify_m=.03,sharp_corner_deg=35.,minimum_world_cut_separation_m=.5,
        minimum_local_fragment_m=.5,geometry_output='original_polyline_substrings',
        raw_source_unchanged=True,approved_for_release=False)
    value['sha256']=digest(value)
    return value


def feature_cuts(points,pol):
    p,s=arc(points);length=s[-1];line=LineString(p);closed=np.linalg.norm(p[0]-p[-1])<1e-10
    candidates=[(0.,100,'source_start'),(float(length),100,'source_end')]
    helper=np.asarray(line.simplify(pol['helper_simplify_m'],preserve_topology=True).coords)
    count=len(helper)-1 if closed else len(helper)
    for i in range(0 if closed else 1,count if closed else count-1):
        a=helper[i]-helper[(i-1)%count];b=helper[(i+1)%count]-helper[i]
        norm=np.linalg.norm(a[:2])*np.linalg.norm(b[:2])
        if norm<=1e-12:continue
        angle=np.degrees(np.arccos(np.clip(np.dot(a[:2],b[:2])/norm,-1,1)))
        if angle>=pol['sharp_corner_deg']:
            from shapely.geometry import Point
            candidates.append((float(line.project(Point(helper[i]))),20,'sharp_corner'))
    ss=np.arange(pol['sample_step_m'],length,pol['sample_step_m'])
    half=pol['tangent_window_m']/2
    if len(ss):
        lo=ss-half;hi=ss+half
        lo=np.mod(lo,length) if closed else np.clip(lo,0,length)
        hi=np.mod(hi,length) if closed else np.clip(hi,0,length)
        center=at(p,s,ss);left=center-at(p,s,lo);right=at(p,s,hi)-center
        norms=np.linalg.norm(left[:,:2],axis=1)*np.linalg.norm(right[:,:2],axis=1)
        angles=np.degrees(np.arccos(np.clip(np.sum(left[:,:2]*right[:,:2],axis=1)/np.maximum(norms,1e-15),-1,1)))
        active=(angles>=pol['turn_threshold_deg'])&(norms>1e-12)
        # Bound curved runs; do not turn every tessellation vertex into an instance.
        transitions=np.diff(np.r_[False,active,False].astype(int))
        for first,last in zip(np.flatnonzero(transitions==1),np.flatnonzero(transitions==-1)-1):
            candidates.extend([(max(0.,float(ss[first]-half)),10,'tight_turn_entry'),
                               (min(float(length),float(ss[last]+half)),10,'tight_turn_exit')])
    accepted=[(0.,100,'source_start'),(float(length),100,'source_end')]
    for value,priority,reason in sorted(candidates,key=lambda x:(-x[1],x[0],x[2])):
        if priority==100:continue
        if all(abs(value-old[0])>=pol['minimum_world_cut_separation_m'] for old in accepted):
            accepted.append((value,priority,reason))
    accepted.sort()
    return accepted


def make_partition(parent,pol):
    p,s=arc(parent['points_xyz']);length=float(s[-1])
    cuts=feature_cuts(p,pol) if pol['feature_split'] else [(0.,100,'source_start'),(length,100,'source_end')]
    if pol['max_length_m']:
        extra=[]
        for a,b in zip(cuts,cuts[1:]):
            n=int(math.ceil((b[0]-a[0])/pol['max_length_m']))
            extra.extend((float(x),5,'maximum_length') for x in np.linspace(a[0],b[0],n+1)[1:-1])
        cuts=sorted(cuts+extra)
    children=[]
    for index,(a,b) in enumerate(zip(cuts,cuts[1:])):
        uid=parent['id']+'/segment/'+digest([pol['sha256'],a[0],b[0]])[:20]
        children.append(dict(id=uid,parent_id=parent['id'],policy_sha256=pol['sha256'],
            world_s_start=a[0],world_s_end=b[0],cut_start_reason=a[2],cut_end_reason=b[2],
            parent_was_closed=bool(np.linalg.norm(p[0]-p[-1])<1e-10),
            points_xyz=subline(p,a[0],b[0]).tolist()))
    return children


def check_partition(parent,children,pol):
    p,s=arc(parent['points_xyz']);end=0.;lines=[]
    require(bool(children),'PARTITION_CHILDREN_MISSING')
    for c in children:
        require(c['parent_id']==parent['id'] and c['policy_sha256']==pol['sha256'],'PARTITION_PARENT_POLICY')
        require(abs(c['world_s_start']-end)<=1e-8,'PARTITION_GAP_OR_OVERLAP')
        expected=subline(p,c['world_s_start'],c['world_s_end'])
        actual=np.asarray(c['points_xyz'])
        require(actual.shape==expected.shape and np.allclose(actual,expected,atol=1e-9,rtol=0),
                'PARTITION_NOT_ORIGINAL_XYZ_SUBSTRING')
        end=c['world_s_end'];lines.append(LineString(actual))
    require(abs(end-s[-1])<=1e-8,'PARTITION_TAIL_MISSING')
    hd=LineString(p).hausdorff_distance(unary_union(lines))
    length_error=abs(sum(x.length for x in lines)-s[-1])
    require(hd<=1e-5 and length_error<=1e-4,'PARTITION_GEOMETRY_COVERAGE')
    return dict(parent_id=parent['id'],children=len(children),hausdorff_m=hd,length_error_m=length_error)
