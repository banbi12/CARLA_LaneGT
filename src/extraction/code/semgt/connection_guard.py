"""Conservative guards for generated bridges; never filter observed paint."""
from pathlib import Path
from functools import lru_cache
import heapq
import numpy as np
from shapely.geometry import LineString,Point
from shapely.ops import substring,unary_union
from .geometry import sample,tangent
from .io import load,sha


def endpoint_provenance(feature,side):
    records=feature.get('endpoint_provenance')
    return records[side] if records else feature.get('stroke_provenance',{})


def unsafe_fragment(feature,side=-1):
    return bool(endpoint_provenance(feature,side).get('unsafe_short_component_fragment'))


def straight_extension(a,b,pa,pb,ta,tb,gap,policy,unsafe_ends=False):
    """Extra distance requires real repeated paint and two-sided collinearity."""
    chord=(pb[0]-pa[-1])/gap
    threshold=np.cos(np.deg2rad(policy['dash_straight_max_angle_deg']))
    angles=min(float(ta@chord),float(tb@chord))
    lateral=max(abs(float(np.cross(ta,pb[0]-pa[-1]))),abs(float(np.cross(tb,pb[0]-pa[-1]))))
    lengths=a.get('observed_run_lengths_m',[])+b.get('observed_run_lengths_m',[])
    repeat=any(len([q for q in f.get('connections',[]) if q.get('kind')=='observed_dash_continuation_C1'])>=2 for f in [a,b])
    supported=(gap<=policy['dash_straight_max_gap_m'] and angles>=threshold and
               lateral<=policy['dash_straight_max_lateral_m'] and
               len(lengths)>=policy['dash_straight_min_observed_runs'] and repeat and
               not unsafe_ends)
    return bool(supported),dict(endpoint_min_chord_dot=angles,maximum_lateral_m=lateral,
                               observed_runs=len(lengths),repeat_evidence=repeat)


def observed_end_window(feature,oriented,start=False):
    end=oriented[0] if start else oriented[-1]
    candidates=[]
    for segment in feature.get('observed_segments_xyz',[]):
        p=np.asarray(segment,float)[:,:2]
        if len(p)<2:continue
        for reversed_ in [False,True]:
            q=p[::-1] if reversed_ else p
            distance=float(np.linalg.norm(q[-1]-end))
            if distance<.15:candidates.append((distance,q))
    if not candidates:return None
    q=min(candidates,key=lambda x:x[0])[1];line=LineString(q)
    if line.length<.3:return None
    return substring(line,max(0,line.length-1.),line.length)


class ConnectionReference:
    """Pinned, map-matched XODR paint curves, separate from optional hints."""
    def __init__(self,world,file_sha256=None):
        if world.get('schema')!='xodr_connection_reference_v1' or not world.get('xodr_sha256'):
            raise ValueError('Invalid connection-reference identity')
        self.map_hash=world['xodr_sha256'];self.file_sha256=file_sha256
        features=list(world['features'].values())
        if any(f.get('class')!='divider' for f in features):raise ValueError('Divider-only connection reference required')
        self.ids=[];self.lines=[]
        for f in features:
            points=np.asarray(f['points_xyz'],float)
            if points.ndim!=2 or points.shape[1]!=3 or len(points)<2 or not np.isfinite(points).all() or np.max(abs(points[:,2]))>1e-6:
                raise ValueError('Invalid flat XODR curve')
            line=LineString(points[:,:2])
            if line.length<=.05:raise ValueError('Degenerate XODR curve')
            self.ids.append(f['id']);self.lines.append(line)
        self.bounds=np.asarray([p.bounds for p in self.lines]).reshape((-1,4))
        self.adjacency={};ends=[]
        for i,line in enumerate(self.lines):
            ends.extend([(i,0,np.asarray(line.coords[0]),tangent(line,0)),
                         (i,1,np.asarray(line.coords[-1]),tangent(line,line.length))])
        for i,side,point,vector in ends:
            node=(i,side);self.adjacency[node]=[((i,1-side),self.lines[i].length)]
            for j,other,q,v in ends:
                if i!=j and np.linalg.norm(point-q)<=.5 and abs(vector@v)>.85:
                    self.adjacency[node].append(((j,other),float(np.linalg.norm(point-q))))

    def validate_map(self,meta):
        if meta.get('xodr_sha256')!=self.map_hash:raise ValueError('XODR connection-reference map mismatch')

    def describe(self):
        return dict(status='validated_connection_reference',xodr_sha256=self.map_hash,
                    file_sha256=self.file_sha256,curves=len(self.lines),scope='generated_uncertain_bridges_only')

    def associate(self,window,policy):
        if window is None or not self.lines:return None
        radius=policy['dash_xodr_endpoint_distance_m'];x0,y0,x1,y1=window.bounds;b=self.bounds
        nearby=np.flatnonzero((b[:,0]<=x1+radius)&(b[:,2]>=x0-radius)&(b[:,1]<=y1+radius)&(b[:,3]>=y0-radius))
        ss,xy=sample(window,.15);vectors=np.asarray([tangent(window,float(s)) for s in ss]);scores=[]
        alignment=np.cos(np.deg2rad(policy['dash_xodr_endpoint_angle_deg']))
        for index in nearby:
            line=self.lines[int(index)];positions=np.asarray([line.project(Point(p)) for p in xy])
            distances=np.asarray([line.distance(Point(p)) for p in xy]);vv=np.asarray([tangent(line,float(s)) for s in positions])
            dots=np.abs((vectors*vv).sum(axis=1));support=float(((distances<=radius)&(dots>=alignment)).mean())
            if support<.8 or distances.max()>radius*1.5:continue
            score=float(np.median(distances)+.25*(1-dots.mean()))
            scores.append(dict(index=int(index),id=self.ids[int(index)],score=score,support=support,
                               position=float(line.project(window.interpolate(window.length)))))
        scores.sort(key=lambda x:(x['score'],x['id']))
        if not scores:return None
        if len(scores)>1 and scores[1]['score']-scores[0]['score']<policy['dash_xodr_endpoint_margin_m']:return None
        return scores[0]

    def route(self,a,b,maximum):
        i,j=a['index'],b['index'];s,t=a['position'],b['position']
        if i==j:return [i] if abs(s-t)<=maximum else None
        goals={(j,0):t,(j,1):self.lines[j].length-t};heap=[];best={}
        for node,distance in [((i,0),s),((i,1),self.lines[i].length-s)]:heapq.heappush(heap,(distance,node,(i,)))
        while heap:
            distance,node,path=heapq.heappop(heap)
            if distance>maximum or distance>=best.get(node,float('inf')):continue
            best[node]=distance
            if node in goals and distance+goals[node]<=maximum:return list(dict.fromkeys(path+(j,)))
            for neighbor,cost in self.adjacency[node]:
                heapq.heappush(heap,(distance+cost,neighbor,path+(neighbor[0],)))
        return None

    def assess(self,a,b,pa,pb,curve,ta,tb,policy):
        gap=float(np.linalg.norm(pb[0]-pa[-1]));chord=(pb[0]-pa[-1])/gap
        uncertain=min(float(ta@chord),float(tb@chord))<np.cos(np.deg2rad(policy['dash_xodr_uncertain_angle_deg']))
        if gap<policy['dash_xodr_min_gap_m'] or not uncertain:
            return dict(decision='neutral',reason='observed_geometry_not_ambiguous')
        left=self.associate(observed_end_window(a,pa),policy)
        right=self.associate(observed_end_window(b,pb,True),policy)
        if left is None or right is None:
            return dict(decision='neutral',reason='no_unique_map_endpoint_evidence',
                        endpoint_ids=[left['id'] if left else None,right['id'] if right else None])
        route=self.route(left,right,2*gap+2.)
        common=dict(endpoint_ids=[left['id'],right['id']],endpoint_support=[left['support'],right['support']])
        if route is None:return dict(common,decision='conflict',reason='xodr_endpoints_without_short_compatible_route')
        corridor=unary_union([self.lines[i] for i in route]);line=LineString(curve);ss,xy=sample(line,.15)
        distance=np.asarray([corridor.distance(Point(p)) for p in xy]);bad=distance>policy['dash_xodr_bridge_max_deviation_m']
        cuts=np.flatnonzero(np.diff(np.r_[False,bad,False].astype(int)))
        longest=max([float(ss[min(hi,len(ss)-1)]-ss[max(0,lo-1)]) for lo,hi in zip(cuts[::2],cuts[1::2])]+[0.])
        conflict=longest>policy['dash_xodr_bad_run_m']
        return dict(common,decision='conflict' if conflict else 'supported',
            reason='xodr_generated_bridge_path_conflict' if conflict else 'xodr_compatible_generated_bridge',
            route_ids=[self.ids[i] for i in route],maximum_deviation_m=float(distance.max()),bad_run_m=longest)


@lru_cache(maxsize=4)
def _load_pinned(asset,pin_path,map_path):
    pin=load(pin_path)
    if sha(Path(asset))!=pin['sha256'] or sha(Path(map_path))!=pin['xodr_sha256']:
        raise ValueError('Connection-reference file/map fingerprint mismatch')
    world=load(asset)
    if world['xodr_sha256']!=pin['xodr_sha256']:raise ValueError('Connection-reference map identity mismatch')
    return ConnectionReference(world,pin['sha256'])


def load_connection_reference(project,meta):
    reference=_load_pinned(str((project/'source_geometry/xodr_connection_prior.json').resolve()),
        str((project/'config/connection_prior.json').resolve()),str((project/'capture_template/evidence/server_Town10HD.xodr').resolve()))
    reference.validate_map(meta)
    return reference
