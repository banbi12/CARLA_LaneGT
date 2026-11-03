"""Selective ISM hiding with native semantic-proxy refresh, synchronized three-sensor evidence."""
import sys,argparse,time,queue,math,json
from collections import Counter
from pathlib import Path
import numpy as np,carla
from PIL import Image,ImageDraw
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'code'),str(R/'code/base')]
from capture_core import collect_group
from mapgt.common import load,save,require,sha
from mapgt.coordinates import OPTICAL_TO_CARLA

def inventory(w):
 out=[]
 for tag in ['Static','Poles','Fences','Roads','Sidewalks','RoadLines','Ground','Buildings','Walls']:
  for o in w.get_environment_objects(getattr(carla.CityObjectLabel,tag)):
   if tag=='Static' and o.name.startswith('InstancedFoliageActor'):continue
   out.append(dict(name=o.name,label=tag,id=str(o.id),transform=o.transform.get_matrix(),bbox_location=[o.bounding_box.location.x,o.bounding_box.location.y,o.bounding_box.location.z],bbox_extent=[o.bounding_box.extent.x,o.bounding_box.extent.y,o.bounding_box.extent.z]))
 return sorted(out,key=lambda x:(x['label'],x['name']))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=2070);ap.add_argument('--cases');ap.add_argument('--verify-restart',action='store_true');args=ap.parse_args();cases=load(R/'cases.json');allow=load(R/'evidence/selective_occluder_allowlist.json');names={o['name'] for o in allow}
 client=carla.Client('127.0.0.1',args.port);client.set_timeout(30);w=client.get_world();mp=w.get_map();saved=w.get_settings();require(mp.name.endswith('Town10HD_Opt') and not saved.synchronous_mode,'FRESH_MATCHED_MAP')
 xodr=mp.to_opendrive();require(xodr==(R/'evidence/server_Town10HD.xodr').read_text(),'MAP_HASH_OR_GEOMETRY_CHANGED');require(not w.get_actors().filter('vehicle.*'),'UNEXPECTED_VEHICLES')
 settings=w.get_settings();settings.synchronous_mode=True;settings.fixed_delta_seconds=.05;settings.no_rendering_mode=False;w.apply_settings(settings);w.set_weather(carla.WeatherParameters.ClearNoon)
 actors=[];boxes={k:queue.Queue(maxsize=6) for k in ['RGB','SEMANTIC','DEPTH']};attrs={};foliage_hidden=False;selective_hidden=False;normal_exit=False;unloaded_layers=set();layer_variant="A_current"
 def callback(k):
  def put(im):
   try:boxes[k].put_nowait(im)
   except queue.Full:
    try:boxes[k].get_nowait()
    except queue.Empty:pass
    boxes[k].put_nowait(im)
  return put
 def capture(case,out,mode):
  require(not out.exists(),'NO_CAPTURE_OVERWRITE');out.mkdir(parents=True);center=case['center_xy'];tf=carla.Transform(carla.Location(x=float(center[0]),y=float(center[1]),z=float(case.get('capture_z',35))),carla.Rotation(pitch=-90,yaw=float(case.get('capture_yaw',0)),roll=0));w.get_spectator().set_transform(tf)
  for a in actors:a.set_transform(tf)
  images=None;snaps={};buf={k:{} for k in boxes};first=None
  for tick in range(45):
   live=w.tick(30);snap=w.get_snapshot();require(live==snap.frame,'SNAPSHOT_TICK');first=live if first is None else first;snaps[live]=snap;time.sleep(.06)
   for name,q in boxes.items():
    while True:
     try:im=q.get_nowait();buf[name][im.frame]=im
     except queue.Empty:break
    for old in sorted(buf[name])[:-8]:del buf[name][old]
   shared=set.intersection(*(set(b) for b in buf.values()));shared={f for f in shared if f>=first+6 and f in snaps}
   if tick>=12 and shared:
    fid=max(shared);snap=snaps[fid]
    for k,q in boxes.items():
     while not q.empty():q.get_nowait()
     q.put_nowait(buf[k][fid])
    images=collect_group(boxes,fid,snap.timestamp.elapsed_seconds,30,camera_names=('RGB','SEMANTIC','DEPTH'));break
  require(images is not None,'NO_SHARED_FRAME');raw={};matrices={}
  for name,im in images.items():
   mat=np.array(im.transform.get_matrix());require(np.abs(mat-np.array(tf.get_matrix())).max()<.001,'MEASURED_POSE');matrices[name]=mat.tolist();raw[name]=np.frombuffer(im.raw_data,dtype=np.uint8).reshape(im.height,im.width,4).copy()
   if 'selective_ab' in str(out):(out/(name.lower()+'.bgra')).write_bytes(raw[name].tobytes())
  rgb=raw['RGB'][:,:,2::-1];labels=raw['SEMANTIC'][:,:,2];d=raw['DEPTH'];depth=(d[:,:,2].astype(float)+256*d[:,:,1].astype(float)+65536*d[:,:,0].astype(float))/16777215*1000
  Image.fromarray(rgb).save(out/'rgb.png');Image.fromarray(labels).save(out/'semantic_labels.png');images['SEMANTIC'].save_to_disk(str(out/'semantic_palette.png'),carla.ColorConverter.CityScapesPalette);np.save(out/'depth_m.npy',depth.astype(np.float32))
  if 'selective_ab' in str(out):Image.fromarray(d[:,:,2::-1]).save(out/'depth_encoded.png')
  iw=images['RGB'].width;ih=images['RGB'].height;fov=float(images['RGB'].fov);focal=iw/(2*math.tan(math.radians(fov)/2));K=np.array([[focal,0,iw/2],[0,focal,ih/2],[0,0,1]]);opt=np.array(matrices['RGB'])@OPTICAL_TO_CARLA
  counts={str(int(k)):int(n) for k,n in zip(*np.unique(labels,return_counts=True))}
  meta=dict(layer_variant=layer_variant,unloaded_layers=sorted(unloaded_layers),case_id=case['case_id'],map_name=mp.name,xodr_sha256=sha(R/'evidence/server_Town10HD.xodr'),visibility_mode=mode,vegetation_hidden=foliage_hidden,selective_occluders_hidden=selective_hidden,GT_reference_only=True,annotation_version='semantic_primary_v4_development',divider_map_policy='diagnostic_only',GT_model_from_world=case['frame']['transform'],original_source_images_modified=False,frame_id=fid,simulation_timestamp=snap.timestamp.elapsed_seconds,sensor_frame_ids={k:im.frame for k,im in images.items()},sensor_timestamps={k:im.timestamp for k,im in images.items()},measured_sensor_to_world_carla=matrices,optical_to_world_carla=opt.tolist(),intrinsic=K.tolist(),image_size=[iw,ih],fov_deg=fov,camera_blueprint_attributes=attrs,semantic_ids={'Roads':1,'Sidewalks':2,'RoadLines':24},semantic_pixel_counts=counts,depth_encoding='1000*(R+256*G+65536*B)/16777215 meters',requested_quality='Epic',weather='ClearNoon',source_frame_token=case['frame']['token'],selective_allowlist=str(R/'evidence/selective_occluder_allowlist.json'),map_identity_basis=load(R/'RUN_MANIFEST.json')['map_identity_basis'])
  save(out/'metadata.json',meta)
  save(out/'COMPLETE.json',dict(case_id=case['case_id'],synchronized_frame=fid,files={n:sha(out/n) for n in ['rgb.png','semantic_labels.png','semantic_palette.png','depth_m.npy','metadata.json']}))
  print('CAPTURE',mode,case['case_id'],counts,flush=True);return dict(labels=labels,depth=depth,rgb=rgb,meta=meta)
 def refresh():
  w.unload_map_layer(carla.MapLayer.Decals);w.load_map_layer(carla.MapLayer.Decals)
  for _ in range(6):w.tick(30)
 try:
  w.unload_map_layer(carla.MapLayer.Foliage);foliage_hidden=True;unloaded_layers.add("Foliage")
  for _ in range(8):w.tick(30)
  current={o.name:o for o in w.get_environment_objects(carla.CityObjectLabel.Static)};require(names<=set(current),'ALLOWLIST_MISSING_AFTER_FOLIAGE_UNLOAD')
  for ref in allow:
   o=current[ref['name']];require(np.allclose([o.bounding_box.location.x,o.bounding_box.location.y,o.bounding_box.location.z],ref['bbox_location'],atol=.002),'ALLOWLIST_POSE_CHANGED')
  baseline_inventory=inventory(w)
  if not args.verify_restart:save(R/'evidence/selective_environment_before.json',baseline_inventory)
  pilot=load(R/'evidence/calibration_case.json');center=pilot['center_xy'];tf=carla.Transform(carla.Location(x=center[0],y=center[1],z=35),carla.Rotation(pitch=-90))
  for name,bid in [('RGB','sensor.camera.rgb'),('SEMANTIC','sensor.camera.semantic_segmentation'),('DEPTH','sensor.camera.depth')]:
   bp=w.get_blueprint_library().find(bid)
   for key,val in {'image_size_x':'1280','image_size_y':'1280','fov':'65','sensor_tick':'0.05','lens_k':'0','lens_kcube':'0'}.items():
    if bp.has_attribute(key):bp.set_attribute(key,val)
   if name=='RGB' and bp.has_attribute('motion_blur_intensity'):bp.set_attribute('motion_blur_intensity','0')
   a=w.spawn_actor(bp,tf);a.listen(callback(name));actors.append(a);attrs[name]=dict(a.attributes)
  if args.verify_restart:
   fresh=capture(pilot,R/'evidence/selective_ab/fresh_restart_restored','fresh_server_restoration_verification')
   original_labels=np.asarray(Image.open(R/'evidence/selective_ab/before/semantic_labels.png'));a=original_labels==20;b=fresh['labels']==20;iou=float((a&b).sum()/max(1,(a|b).sum()))
   original_inventory=load(R/'evidence/selective_environment_before.json');fresh_inventory=inventory(w)
   physical=lambda rows:Counter(json.dumps({k:x[k] for k in ['label','transform','bbox_location','bbox_extent']},sort_keys=True) for x in rows)
   restored=physical(original_inventory)==physical(fresh_inventory);source_by_name={x['name']:x for x in original_inventory};current_by_name={x['name']:x for x in fresh_inventory}
   selected_poses=all(name in current_by_name and current_by_name[name]['transform']==source_by_name[name]['transform'] and current_by_name[name]['bbox_location']==source_by_name[name]['bbox_location'] for name in names)
   proof=dict(passed=iou>.98 and restored and selected_poses and mp.to_opendrive()==xodr,Static_semantic_mask_IoU=iou,full_registered_physical_inventory_restored=restored,selected_object_poses_restored=selected_poses,selected_objects=len(names),xodr_unchanged=mp.to_opendrive()==xodr,method='Owned server fully stopped and fresh server started on unchanged map; no hot reload. In-process Props reload was experimentally insufficient because these spline actors are not in Props.')
   save(R/'reports/fresh_server_restoration_checks.json',proof);save(R/'evidence/selective_environment_fresh_restart.json',fresh_inventory);require(proof['passed'],'FRESH_SERVER_RESTORATION_FAILED');normal_exit=True;return
  before=capture(pilot,R/'evidence/selective_ab'/('before' if not (R/'evidence/selective_ab/before').exists() else 'before_'+str(int(time.time()))),'foliage_only_baseline')
  runtime_ids={int(current[name].id) for name in names};save(R/'evidence/selective_runtime_ids.json',[str(i) for i in sorted(runtime_ids)]);w.enable_environment_objects(runtime_ids,False);selective_hidden=True;refresh()
  clean=capture(pilot,R/'evidence/selective_ab'/('after' if not (R/'evidence/selective_ab/after').exists() else 'after_'+str(int(time.time()))),'selectively_unoccluded_calibration')
  # Conservative image-space union of the selected objects' projected 3D bounding boxes.
  maskim=Image.new('L',(1280,1280),0);draw=ImageDraw.Draw(maskim);T=np.linalg.inv(np.array(before['meta']['optical_to_world_carla']));K=np.array(before['meta']['intrinsic'])
  for o in allow:
   loc=np.array(o['bbox_location']);ext=np.array(o['bbox_extent']);pts=np.array([loc+ext*np.array([i,j,k]) for i in [-1,1] for j in [-1,1] for k in [-1,1]]);opt=np.c_[pts,np.ones(8)]@T.T;uv=opt[:,:3]@K.T;uv=uv[:,:2]/uv[:,2:3];lo=uv.min(axis=0)-4;hi=uv.max(axis=0)+4
   if hi[0]>=0 and hi[1]>=0 and lo[0]<1280 and lo[1]<1280:draw.rectangle([tuple(lo),tuple(hi)],fill=255)
  mask=np.array(maskim)>0;maskim.save(R/'evidence/selective_ab/allowlist_projection_mask.png');oldstatic=(before['labels']==20)&mask;remaining=oldstatic&(clean['labels']==20);newground=oldstatic&np.isin(clean['labels'],[1,2,24,25])
  yy,xx=np.indices((1280,1280));rays=np.stack((xx,yy,np.ones_like(xx)),axis=-1)@np.linalg.inv(K).T;opt=np.array(before['meta']['optical_to_world_carla']);zbefore=((rays*before['depth'][:,:,None])@opt[:3,:3].T+opt[:3,3])[:,:,2];zafter=((rays*clean['depth'][:,:,None])@opt[:3,:3].T+opt[:3,3])[:,:,2]
  lowered=oldstatic&(zbefore-zafter>.05)&(zafter<.40);tall_before=oldstatic&(zbefore>.4);tall_confirmed=tall_before&(zbefore-zafter>.1)&(zafter<.4);groundids=[1,2,24,25];shared=np.isin(before['labels'],groundids)&np.isin(clean['labels'],groundids)&~mask
  eq=float((before['labels'][shared]==clean['labels'][shared]).mean());delta=float(np.percentile(np.abs(zbefore[shared]-zafter[shared]),99));difference=float(np.abs(before['rgb'].astype(float)-clean['rgb']).mean(axis=2)[oldstatic].mean())
  after_inventory=inventory(w);save(R/'evidence/selective_environment_hidden.json',after_inventory)
  unchanged=[x for x in baseline_inventory if x['name'] not in names];after_unchanged=[x for x in after_inventory if x['name'] not in names];physical=lambda rows:Counter(json.dumps({k:x[k] for k in ['label','transform','bbox_location','bbox_extent']},sort_keys=True) for x in rows);unchanged_ok=physical(unchanged)==physical(after_unchanged)
  proof=dict(selected_objects=len(allow),selected_old_Static_pixels=int(oldstatic.sum()),remaining_Static_at_same_pixels=int(remaining.sum()),new_ground_class_pixels=int(newground.sum()),depth_lowered_to_ground_pixels=int(lowered.sum()),tall_occluder_pixels=int(tall_before.sum()),tall_occluder_depth_confirmed_pixels=int(tall_confirmed.sum()),depth_validation="All selected old Static pixels: >90% lower by >0.05m to z<0.4m; old surfaces z>0.4m: >95% lower by >0.1m to z<0.4m. Low chains need not be >0.25m above sidewalk.",RGB_mean_abs_change_at_selected_pixels=difference,shared_ground_outside_allowlist_pixels=int(shared.sum()),shared_ground_class_agreement_outside_allowlist=eq,shared_ground_height_diff_p99_m=delta,unselected_registered_physical_objects_exactly_unchanged=unchanged_ok,unselected_registry_names_IDs_unchanged=unchanged==after_unchanged,native_re_registration_may_renumber_instanced_object_names=True,unselected_registered_objects_checked=len(unchanged),xodr_unchanged=mp.to_opendrive()==xodr,all_Static_hidden=False,Decals_restored_before_capture=True,semantic_proxy_refresh='native Decals reload invokes TagActorsInLevel.MarkRenderStateDirty',road_object_inventory_empty_not_used_as_proof=True)
  passed=oldstatic.sum()>300 and remaining.sum()/oldstatic.sum()<.1 and newground.sum()/oldstatic.sum()>.8 and lowered.sum()/oldstatic.sum()>.9 and tall_confirmed.sum()/max(1,tall_before.sum())>.95 and difference>2 and eq>.9995 and delta<.02 and unchanged_ok and proof['xodr_unchanged'];proof['passed']=bool(passed);save(R/'reports/selective_pilot_gate.json',proof);require(passed,'SELECTIVE_RGB_SEMANTIC_DEPTH_GATE_FAILED')
  # Reallocate only the synchronized sensor trio, without loading another world.
  for a in actors:a.stop();a.destroy()
  actors.clear()
  for q in boxes.values():
   while not q.empty():q.get_nowait()
  for _ in range(12):w.tick(30)
  for name,bid in [('RGB','sensor.camera.rgb'),('SEMANTIC','sensor.camera.semantic_segmentation'),('DEPTH','sensor.camera.depth')]:
   bp=w.get_blueprint_library().find(bid)
   for key,val in {'image_size_x':'1152','image_size_y':'2048','fov':'36','sensor_tick':'0.05','lens_k':'0','lens_kcube':'0'}.items():
    if bp.has_attribute(key):bp.set_attribute(key,val)
   if name=='RGB' and bp.has_attribute('motion_blur_intensity'):bp.set_attribute('motion_blur_intensity','0')
   a=w.spawn_actor(bp,tf);a.listen(callback(name));actors.append(a);attrs[name]=dict(a.attributes)
  for variant in load(R/'config/layer_variants.json'):
   layer_variant=variant['name']
   for layer in variant['extra_unloaded_layers']:
    if layer in unloaded_layers:continue
    require(layer not in ['Ground','Decals'],'ROAD_EVIDENCE_LAYERS_MUST_REMAIN')
    print('UNLOAD_LAYER',layer,flush=True);w.unload_map_layer(getattr(carla.MapLayer,layer));unloaded_layers.add(layer)
    for _ in range(6):w.tick(30)
   if layer_variant!='A_current':refresh()
   require(mp.to_opendrive()==xodr,'XODR_CHANGED_DURING_LAYER_TOGGLE')
   save(R/'evidence'/('environment_'+layer_variant+'.json'),inventory(w))
   started=time.monotonic()
   for index,case in enumerate(cases):
    out=R/'topdown_cases'/case['case_id']
    if (out/'COMPLETE.json').exists():continue
    if out.exists():out.rename(out.with_name(out.name+'.incomplete_'+str(int(time.time()))))
    capture(case,out,'layer_comparison_'+layer_variant)
    save(R/'reports/capture_progress.json',dict(done=index+1,total=len(cases),last_reference=case['case_id'],elapsed_s=time.monotonic()-started,status='running'))
   save(R/'reports/capture_progress.json',dict(done=len(cases),total=len(cases),elapsed_s=time.monotonic()-started,status='complete'))
   print('VARIANT_COMPLETE',layer_variant,flush=True)
  save(R/'reports/selective_restore_policy.json',dict(in_process_restore_claimed=False,method='Stop owned server, then verify original poses and semantic in a fresh server before accepting delivery',reason='Spline actors are not restored by Props reload; native registry loses original ISM pose after re-registration'));normal_exit=True
 finally:
  for a in actors:
   try:a.stop();a.destroy()
   except RuntimeError:pass
  # Owned disposable world: cold server teardown restores layers without a reload memory surge.
  for _ in range(6):
   try:w.tick(30)
   except RuntimeError:break
  save(R/'reports/selective_cleanup.json',dict(normal_exit=normal_exit,selective_hidden_state_on_child_exit=selective_hidden,in_process_selective_restore_confirmed=not selective_hidden,server_shutdown_reset_required=selective_hidden,foliage_hidden_state_on_exit=foliage_hidden,owned_temporary_server=True,sensors_destroyed=True,restore_requested=True));w.apply_settings(saved)
if __name__=='__main__':main()
