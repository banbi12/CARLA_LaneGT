"""Observed semantic road-sidewalk boundary replacement and conservative divider correction."""
import os,sys,json,gzip,copy,math,time
from pathlib import Path
import numpy as np,cv2
from scipy.spatial import cKDTree
from shapely.geometry import Polygon,LineString,Point,mapping,shape
from shapely.ops import unary_union,linemerge
from PIL import Image,ImageDraw
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'code'))
from mapgt.common import load,save,sha,digest,require
from mapgt.world import check_graph
from mapgt.coordinates import transform
M=load(R/'RUN_MANIFEST.json');P=R

def parts(g):
 if g.is_empty:return
 if g.geom_type=='LineString':yield g
 elif hasattr(g,'geoms'):
  for x in g.geoms:yield from parts(x)
def polys(g):
 if g.is_empty:return
 if g.geom_type=='Polygon':yield g
 elif hasattr(g,'geoms'):
  for x in g.geoms:yield from polys(x)
def project(points,meta):
 p=np.asarray(points,float)
 if p.shape[1]==2:p=np.column_stack((p,np.zeros(len(p))))
 q=transform(np.linalg.inv(np.array(meta['optical_to_world_carla'])),p)@np.array(meta['intrinsic']).T
 return q[:,:2]/q[:,2:3]
def to_world(uv,meta):
 p=np.column_stack((uv,np.ones(len(uv))))@np.linalg.inv(np.array(meta['intrinsic'])).T;t=np.array(meta['optical_to_world_carla']);d=p@t[:3,:3].T;o=t[:3,3]
 return o+d*(-o[2]/d[:,2])[:,None]
def mask_polygons(mask,meta):
 contours,hierarchy=cv2.findContours(mask.astype(np.uint8),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE);result=[]
 if hierarchy is None:return Polygon()
 for i,c in enumerate(contours):
  if hierarchy[0,i,3]!=-1 or len(c)<3:continue
  outer=to_world(c[:,0,:],meta)[:,:2];holes=[];child=hierarchy[0,i,2]
  while child!=-1:
   h=contours[child]
   if len(h)>=3:holes.append(to_world(h[:,0,:],meta)[:,:2])
   child=hierarchy[0,child,0]
  poly=Polygon(outer,holes)
  if not poly.is_valid:poly=poly.buffer(0)
  if not poly.is_empty:result.append(poly)
 return unary_union(result).simplify(.02,preserve_topology=True) if result else Polygon()
def split_valid(coords,valid):
 # Split at any unobserved stretch; no tree/building/image-edge contours enter GT.
 if len(coords)<2:return
 cuts=np.flatnonzero(np.diff(np.r_[False,valid,False].astype(int)))
 for a,b in zip(cuts[::2],cuts[1::2]):
  if b-a>=2:yield coords[a:b]
def ordered_parts(geometry,original):
 line=LineString(original);rows=[]
 for part in parts(geometry):
  xyz=np.array(part.coords)
  if xyz.shape[1]==2:xyz=np.column_stack((xyz,np.zeros(len(xyz))))
  a=line.project(Point(xyz[0]));b=line.project(Point(xyz[-1]))
  if b<a:xyz=xyz[::-1];a,b=b,a
  if LineString(xyz).length>.05:rows.append((a,b,xyz))
 return sorted(rows,key=lambda x:x[0])
def sample_line(line,step=.05):return np.array([line.interpolate(s).coords[0] for s in np.linspace(0,line.length,max(2,int(line.length/step)+1))])
def paint(im,points,meta,color,width=2):
 uv=project(points,meta)
 if np.isfinite(uv).all():ImageDraw.Draw(im).line([tuple(p) for p in uv],fill=color,width=width)

def extract_boundary(case,meta,labels,depth,original,out):
 global R
 R=out
 world=original;cases=[case];observations=[];owned_union=Polygon();all_roads=[];semantic_segments=[];allpaint=[];skipped=[];maskrows=[]
 for case in cases:
  cid=case['case_id'];ids=meta['semantic_ids'];h,w=labels.shape
  yy,xx=np.indices((h,w));rays=np.stack((xx,yy,np.ones_like(xx)),axis=-1)@np.linalg.inv(np.array(meta['intrinsic'])).T;t=np.array(meta['optical_to_world_carla']);height=(rays*depth[:,:,None])@t[:3,:3].T+t[:3,3]
  ground=np.isfinite(depth)&(height[:,:,2]>-.08)&(height[:,:,2]<.40)
  road=((labels==ids['Roads'])|(labels==ids['RoadLines']))&ground;known=(road|(labels==ids['Sidewalks']))&ground
  known[:48]=False;known[-48:]=False;known[:,:48]=False;known[:,-48:]=False
  known=cv2.erode(known.astype(np.uint8),np.ones((3,3),np.uint8))>0
  coverage=mask_polygons(known,meta);owned=coverage.difference(owned_union);owned_union=unary_union([owned_union,coverage]);roadpoly=mask_polygons(road,meta).intersection(owned)
  all_roads.append(roadpoly)
  side_near=cv2.dilate((labels==ids['Sidewalks']).astype(np.uint8),np.ones((5,5),np.uint8))>0
  contours,_=cv2.findContours(road.astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE);source_count=0
  for ci,contour in enumerate(contours):
   uv=contour[:,0,:];valid=known[uv[:,1],uv[:,0]]&side_near[uv[:,1],uv[:,0]]
   if valid.all():runs=[np.vstack((uv,uv[0]))]
   else:
    # Rotate at a genuinely unobserved pixel; a fully observed island stays closed.
    pivot=int(np.flatnonzero(~valid)[0]);uv=np.roll(uv,-pivot,axis=0);valid=np.roll(valid,-pivot);runs=split_valid(uv,valid)
   for ri,run in enumerate(runs):
    xyz=to_world(run,meta);raw=LineString(xyz);simple=raw.simplify(.04,preserve_topology=True)
    require(raw.hausdorff_distance(simple)<=.040001,'SEMANTIC_RASTER_APPROXIMATION')
    for li,line in enumerate(parts(simple.intersection(owned))):
     if line.length<=.05:
      skipped.append(dict(case_id=cid,reason='source_fragment_le_0.05m',length_m=line.length));continue
     coords=np.array(line.coords);coords=np.column_stack((coords[:,:2],np.zeros(len(coords))))
     semantic_segments.append(dict(points_xyz=coords.tolist(),cases=[cid],source_id=f'{cid}/contour{ci}/run{ri}/part{li}'));source_count+=1
  py,px=np.where((labels==ids['RoadLines'])&ground&known)
  if len(px):allpaint.extend(to_world(np.column_stack((px,py)),meta)[:,:2].tolist())
  observations.append(dict(case_id=cid,metadata=meta,coverage=coverage,owned=owned,road=roadpoly,known_mask=known,labels=labels))
  maskrows.append(dict(case_id=cid,visible_ground_area_m2=coverage.area,owned_area_m2=owned.area,semantic_boundary_parts=source_count))
  print('SEMANTIC_SOURCE',cid,'owned_m2',round(owned.area,1),'curb_parts',source_count,flush=True)
 road_domain=unary_union(all_roads);save(R/'evidence/observed_coverage.json',mapping(owned_union));save(R/'evidence/observed_road_domain.json',mapping(road_domain));save(R/'reports/observation_coverage.json',maskrows)
 # Reconcile only sub-0.1m raster seams with aligned tangent directions. No long occlusion bridging.
 merges=[];changed=True
 while changed:
  changed=False
  for i in range(len(semantic_segments)):
   if changed:break
   a=np.array(semantic_segments[i]['points_xyz'])
   if np.array_equal(a[0],a[-1]):continue
   for j in range(i+1,len(semantic_segments)):
    b=np.array(semantic_segments[j]['points_xyz']);found=False
    if np.array_equal(b[0],b[-1]):continue
    for ai in (0,-1):
     for bj in (0,-1):
      distance=np.linalg.norm(a[ai,:2]-b[bj,:2])
      if distance>.10:continue
      aa=a if ai==-1 else a[::-1];bb=b if bj==0 else b[::-1]
      va=aa[-1,:2]-aa[max(0,len(aa)-3),:2];vb=bb[min(2,len(bb)-1),:2]-bb[0,:2]
      norm=np.linalg.norm(va)*np.linalg.norm(vb)
      if norm<1e-9 or np.dot(va,vb)/norm<math.cos(math.radians(25)):continue
      midpoint=(aa[-1]+bb[0])/2
      if not owned_union.buffer(.03).covers(Point(midpoint)):continue
      points=np.vstack((aa[:-1],midpoint,bb[1:]));line=LineString(points)
      if not line.is_simple:continue
      sources=semantic_segments[i]['cases']+semantic_segments[j]['cases'];merged=dict(points_xyz=points.tolist(),cases=sorted(set(sources)),source_id=semantic_segments[i]['source_id']+'+'+semantic_segments[j]['source_id'])
      merges.append(dict(sources=merged['source_id'],gap_m=float(distance),reason='aligned semantic raster seam only'))
      semantic_segments[i]=merged;semantic_segments.pop(j);changed=True;found=True;break
     if found:break
    if changed:break
 semantic_boundary=unary_union([LineString(x['points_xyz']) for x in semantic_segments]);save(R/'reports/semantic_seam_merges.json',merges)
 newworld=copy.deepcopy(world);operations=[];divider_audit=[];kept_boundary=[]
 def add_feature(cls,points,source,original_parent_id=None):
  coords=np.asarray(points);uid=cls+':semantic_revision:'+digest(dict(points=coords.tolist(),source=source))[:24]
  feature=dict(id=uid,**{'class':cls},source=source,points_xyz=coords.tolist(),geometry_revision_sha256=digest(coords.tolist()),human_approved=False)
  if original_parent_id:feature['original_parent_id']=original_parent_id
  newworld['features'][uid]=feature;return feature
 # Remove old boundary only where the flat ground and Road/Sidewalk observations are reliable.
 for parent in list(world['features'].values()):
  if parent['class']!='boundary':continue
  line=LineString(parent['points_xyz']);remaining=line.difference(owned_union)
  if line.difference(remaining).length<=1e-7:continue
  del newworld['features'][parent['id']];children=[]
  for lo,hi,xyz in ordered_parts(remaining,parent['points_xyz']):
   f=add_feature('boundary',xyz,dict(kind='original_boundary_unobserved_remainder',original_source=parent['source'],original_parent_id=parent['id'],original_arc_interval_m=[lo,hi]),parent['id']);children.append(f);kept_boundary.append(f)
  operations.append(dict(op='replace_observed_boundary',target_id=parent['id'],before=parent,after_ids=[f['id'] for f in children],removed_observed_length_m=float(line.length-remaining.length),status='pending'))
 for segment in semantic_segments:
  add_feature('boundary',segment['points_xyz'],dict(kind='observed_semantic_road_sidewalk_boundary',case_ids=segment['cases'],contour_source=segment['source_id'],
    palette_color_not_used=True,road_ids=[1,24],sidewalk_id=2,ground_z_range_m=[-.08,.40],raster_simplification_limit_m=.04,source_run=str(P),map_identity_basis=M['map_identity_basis']))
 return [f for f in newworld['features'].values() if f['class']=='boundary'],maskrows,merges,skipped
