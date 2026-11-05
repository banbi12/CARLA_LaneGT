"""Adopted 0.35m/no-angle repair; no old-centerline stop deletion or map-ID barrier."""
import copy,math

import numpy as np,cv2

from shapely.geometry import LineString,Point

from shapely.ops import substring

from scipy.spatial import cKDTree

from scipy.interpolate import CubicHermiteSpline

def runs(mask):
 c=np.flatnonzero(np.diff(np.r_[False,mask,False].astype(int)));return zip(c[::2],c[1::2])

def project(p,m):
 p=np.asarray(p);p=np.c_[p[:,:2],np.zeros(len(p))];q=np.c_[p,np.ones(len(p))]@np.linalg.inv(np.array(m['optical_to_world_carla'])).T;v=q[:,:3]@np.array(m['intrinsic']).T;return v[:,:2]/v[:,2:3]

def sample(l,step=.04):
 ss=np.linspace(0,l.length,max(2,int(np.ceil(l.length/step))+1));return ss,np.array([l.interpolate(s).coords[0] for s in ss])[:,:2]

def tangent(l,s,window=.3):
 a=np.array(l.interpolate(max(0,s-window)).coords[0])[:2];b=np.array(l.interpolate(min(l.length,s+window)).coords[0])[:2];v=b-a;return v/max(np.linalg.norm(v),1e-12)

def endpoint(p,start=False):
 p=np.asarray(p)[:,:2];l=LineString(p);return tangent(l,0 if start else l.length,.7)

def merge_intervals(ranges):
 out=[]
 for a,b in sorted(ranges):
  if out and a<=out[-1][1]+1e-8:out[-1][1]=max(b,out[-1][1])
  else:out.append([a,b])
 return out

def fill_small_gaps(features,m,lab,depth,zebra,stop_mask,allowed_classes=('boundary','divider'),max_gap_m=.35,min_tangent_chord_dot=None,max_curve_chord_ratio=None):
 out=copy.deepcopy(features);audit=[];reject=[];scale=float(m['optical_to_world_carla'][2][3])/m['intrinsic'][0][0];radius=max(1,int(np.ceil(.12/scale)));kernel=np.ones((radius*2+1,radius*2+1),np.uint8);road=cv2.dilate(np.isin(lab,[1,24]).astype(np.uint8),kernel)>0;side=cv2.dilate((lab==2).astype(np.uint8),kernel)>0
 for f in out:
  if f['class_name'] in ['boundary','divider']:f.setdefault('pre_gap_geometries_xyz',[f['points_xyz']])
 for iteration in range(150):
  options=[]
  for i,a in enumerate(out):
   if a['class_name'] not in allowed_classes:continue
   if np.allclose(a['points_xyz'][0],a['points_xyz'][-1],atol=1e-8):continue
   for j in range(i+1,len(out)):
    b=out[j]
    if a['class_name']!=b['class_name']:continue
    if np.allclose(b['points_xyz'][0],b['points_xyz'][-1],atol=1e-8):continue
    if a['class_name']=='divider' and a.get('mark_type')!=b.get('mark_type'):continue
    la=LineString(np.array(a['points_xyz'])[:,:2]);lb=LineString(np.array(b['points_xyz'])[:,:2])
    if la.intersection(lb.buffer(.04)).length>min(.5,.8*min(la.length,lb.length)):continue
    for ra in [False,True]:
     pa=np.array(a['points_xyz'])[::(-1 if ra else 1),:2]
     for rb in [False,True]:
      pb=np.array(b['points_xyz'])[::(-1 if rb else 1),:2];v=pb[0]-pa[-1];gap=float(np.linalg.norm(v))
      if not .015<gap<=max_gap_m:continue
      ta=endpoint(pa);tb=endpoint(pb,True);chord=v/gap
      if min_tangent_chord_dot is not None and min(float(ta@chord),float(tb@chord))<min_tangent_chord_dot:continue
      spline=CubicHermiteSpline([0,gap],np.stack([pa[-1],pb[0]]),np.stack([ta,tb]));curve=spline(np.linspace(0,gap,max(5,int(gap/.02)+1)));line=LineString(curve)
      if max_curve_chord_ratio is not None and line.length/gap>max_curve_chord_ratio:continue
      uv=project(curve,m).round().astype(int);h,w=lab.shape
      if np.any((uv[:,0]<48)|(uv[:,0]>=w-48)|(uv[:,1]<48)|(uv[:,1]>=h-48)):continue
      x,y=uv[:,0],uv[:,1]
      if np.any(stop_mask[y,x]):reject.append(dict(reason='stopline_barrier',class_name=a['class_name'],gap_m=gap));continue
      if a['class_name']=='divider' and np.any(zebra[y,x]):continue
      labels=lab[y,x]
      if not np.isin(labels,[1,2,24,6,7,8,9,11,20,22]).all():continue
      if a['class_name']=='boundary':
       if np.mean(road[y,x]&side[y,x])<.8:continue
      elif np.mean(road[y,x])<.8 or np.any(np.isin(labels,[2,25])):continue
      # Crossing an existing boundary/divider within the bridge interior is forbidden.
      interior=LineString(curve[1:-1]) if len(curve)>3 else line;blocked=False
      for k,q in enumerate(out):
       if k in (i,j) or q['class_name'] not in ['boundary','divider']:continue
       if interior.intersects(LineString(np.array(q['points_xyz'])[:,:2])):blocked=True;break
      if blocked:continue
      joined=np.vstack([pa,curve[1:-1],pb]);joinedline=LineString(joined)
      if not joinedline.is_simple:continue
      options.append(dict(i=i,j=j,ra=ra,rb=rb,gap=gap,cost=gap,pa=pa,pb=pb,curve=curve,labels=labels,joined=joined))
  if not options:break
  endpoint_options={}
  for q in options:
   for e in [(q['i'],0 if q['ra'] else -1),(q['j'],-1 if q['rb'] else 0)]:endpoint_options.setdefault(e,[]).append(q)
  selected=None
  for q in sorted(options,key=lambda x:(x['cost'],x['i'],x['j'])):
   safe=True
   for e in [(q['i'],0 if q['ra'] else -1),(q['j'],-1 if q['rb'] else 0)]:
    qq=sorted(endpoint_options[e],key=lambda x:x['cost'])
    if qq[0] is not q:safe=False;break
    if len(qq)>1 and qq[1]['cost']-q['cost']<.05 and qq[1]['cost']<q['cost']*1.5:safe=False;break
   if safe:selected=q;break
  if selected is None:break
  q=selected;i,j=q['i'],q['j'];a=out[i];b=out[j];vals,cnt=np.unique(q['labels'],return_counts=True);record=dict(kind='small_occlusion_or_raster_gap',class_name=a['class_name'],source_ids=[a['id'],b['id']],gap_m=q['gap'],points_xy=q['curve'].tolist(),uv=project(q['curve'],m).tolist(),bridge_labels=dict(zip(vals.astype(str),cnt.astype(int).tolist())),old_vertices_preserved=True,mutual_unique_endpoints=True,stopline_barrier_passed=True,angle_rejection_enabled=False,tangent_difference_deg=float(np.degrees(np.arccos(np.clip(np.dot(endpoint(q['pa']),endpoint(q['pb'],True)),-1,1)))),tangent_chord_min_alignment=float(min(np.dot(endpoint(q['pa']),(q['pb'][0]-q['pa'][-1])/q['gap']),np.dot(endpoint(q['pb'],True),(q['pb'][0]-q['pa'][-1])/q['gap']))),curve_to_chord_ratio=float(LineString(q['curve']).length/q['gap']))
  a.update(points_xyz=np.c_[q['joined'],np.zeros(len(q['joined']))].tolist(),uv=project(q['joined'],m).tolist(),pre_gap_geometries_xyz=a['pre_gap_geometries_xyz']+b['pre_gap_geometries_xyz'],connections=a.get('connections',[])+b.get('connections',[])+[record],gap_repaired=True);out.pop(j);audit.append(record)
 return out,audit,reject
