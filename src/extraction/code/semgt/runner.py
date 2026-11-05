"""Explicit on-demand extraction, never executed by checks or collect dry-run."""
from pathlib import Path
import copy,os,subprocess,sys
import numpy as np
from PIL import Image
from .io import load,save,sha,fresh_output
from .engine import dividers,assemble,repair_boundaries
from .crosswalks import select
from .sampling import actual_targets,diagnostics
from . import VERSION

def reference(row,paths,project,out,policy,old_world=None,reference_case=None):
    source=Path(paths['topdown_root'])/row['reference'];proof=load(source/'COMPLETE.json')
    for file,digest in proof['files'].items():
        if sha(source/file)!=digest:raise ValueError('Reference hash mismatch: '+str(source/file))
    meta=load(source/'metadata.json')
    from .input_contract import validate
    validate(row,meta,reference_case,load(project/'source_geometry/xodr_crosswalk_world.json')['xodr_sha256'])
    from .bev import coverage
    coverage_report=coverage(meta,row['transform'],row.get('BEV_range_m'),policy['border_px'])
    meta=dict(meta,GT_model_from_world=copy.deepcopy(row['transform']))
    labels=np.asarray(Image.open(source/'semantic_labels.png'));depth=np.load(source/'depth_m.npy');rgb=np.asarray(Image.open(source/'rgb.png').convert('RGB'))
    connection_reference=None
    if policy['connection_guards_enabled'] and policy['connection_use_xodr']:
        from .connection_guard import load_connection_reference
        connection_reference=load_connection_reference(project,meta)
    divider_base=None
    if policy.get('divider_base_mode')=='xodr_v41':
        from .connection_guard import load_divider_base
        divider_base=load_divider_base(project,meta)
    features,audit,hints=dividers(meta,labels,depth,rgb,policy,old_world,connection_reference,divider_base)
    import boundary_core
    case=dict(case_id=row['reference'])
    # The observed boundary geometry is unchanged; old boundary remnants are never input.
    boundaries,coverage,seams,skipped=boundary_core.extract_boundary(case,meta,labels,depth,dict(features={}),out/'boundary')
    for f in boundaries:
        features.append(dict(id=f['id'],class_name='boundary',points_xyz=f['points_xyz'],source=f['source'],review='pending'))
    crossings=load(project/'source_geometry/xodr_crosswalk_world.json')
    features+=select(crossings,row['transform'],meta,row.get('BEV_range_m'))
    features,boundary_gaps,boundary_rejected=repair_boundaries(features,meta,labels,depth,audit['observed_crosswalk_mask'],policy)
    audit['boundary_small_gap_connections']=boundary_gaps
    audit['boundary_smooth_gap_connections']=[record for record in boundary_gaps if record.get('boundary_smooth_connection')]
    audit['small_gap_connections']+=boundary_gaps
    audit['rejected_connections']+=boundary_rejected
    stripe_mask=audit.pop('observed_crosswalk_mask');Image.fromarray((stripe_mask*255).astype(np.uint8)).save(out/'observed_crosswalk_paint_mask.png')
    save(out/'candidates.json',features);save(out/'audit.json',audit);save(out/'optional_map_hints.json',hints)
    save(out/'reference_manifest.json',dict(reference=row['reference'],source=str(source),source_complete_sha256=sha(source/'COMPLETE.json'),version=VERSION,map_hints_affect_geometry=False,
        xodr_connection_constraints=connection_reference.describe() if connection_reference is not None else None,
        BEV_coverage=coverage_report,boundary_coverage=coverage,boundary_seams=seams,boundary_skipped=skipped))
    return features

def run(project,paths,rows,output,policy,old_world=None,use_sampler=False,centerline_mode="none",bev_range=None,topdown_only=False,centerline_world=None):
    os.environ['CUDA_VISIBLE_DEVICES']=''
    from .bev import bounds
    bev_range=bounds(bev_range);rows=copy.deepcopy(rows)
    for row in rows:
        row['BEV_range_m']=bev_range
        if topdown_only:row['image_paths']={}
    protected=[paths['topdown_root'],Path(paths['frame_manifest']).parent,paths['native_images'],paths['native_metadata'],paths['native_labels']]+paths.get('protected_output_roots',[])
    from .bev import coverage
    from .input_contract import cases as read_cases,validate
    cases=read_cases(paths)
    expected=load(project/'source_geometry/xodr_crosswalk_world.json')['xodr_sha256']
    for row in rows:
        metadata=load(Path(paths['topdown_root'])/row['reference']/'metadata.json')
        validate(row,metadata,cases.get(row['reference']),expected)
        coverage(metadata,row['transform'],bev_range,policy['border_px'])
    out=fresh_output(output,protected);partition=load(project/'config/boundary_partition_policy.json');completed_references=set();summary=[]
    save(out/'manifest.json',dict(version=VERSION,frames=rows,policy=policy,BEV_range_m=bev_range,centerline_mode=centerline_mode,topdown_only=topdown_only,candidate_only=True,approved_for_training=False,GPU_used=False))
    center_world=None
    if centerline_mode=='generate':
        repository=project.resolve().parents[1]
        target=out/'centerlines_world.json'
        if centerline_world:
            from .centerlines import validate_world
            center_world=validate_world(load(centerline_world),sha(repository/'assets/capture/server_Town10HD.xodr'))
            save(target,center_world)
        else:
            subprocess.run([paths.get('runtime_python',sys.executable),'-B',str(repository/'tools/generate_centerlines.py'),'--output',str(target)],check=True)
            center_world=load(target)
    for row in rows:
        ref=row['reference'];folder=out/'geometry'/ref;folder.mkdir(parents=True,exist_ok=True)
        if ref not in completed_references:
            features=reference(row,paths,project,folder,policy,old_world,cases.get(ref));completed_references.add(ref)
        else:features=load(folder/'candidates.json')
        centerline=[]
        if centerline_mode=='provided':
            centerline=load(Path(paths['native_labels'])/(row['token']+'.json.gz'))['classes']['centerline']
            if bev_range!=[-15.,-30.,15.,30.]:
                from .centerlines import clip_provided
                centerline=clip_provided(centerline,bev_range)
        elif centerline_mode=='generate':
            from .centerlines import local
            centerline=local(center_world,row,bev_range)
        gt,targets=assemble(row,features,centerline,partition)
        sampled=actual_targets(targets,paths['model_root'],bev_range) if use_sampler else None
        if sampled is not None:gt,targets=assemble(row,features,centerline,partition,sampled)
        sampling_report=diagnostics(targets,sampled) if sampled is not None else dict(status='not_run_diagnostic_only')
        frame=out/'frames'/row['token'];frame.mkdir(parents=True,exist_ok=False);gt.update(centerline_mode=centerline_mode,centerline_exact_from_source=centerline_mode=='provided' and bev_range==[-15.,-30.,15.,30.])
        save(frame/'gt.json.gz',gt)
        if sampled is not None:np.savez_compressed(frame/'actual_sampler_targets.npz',target_ids=np.asarray([f['id'] for f in targets]),**sampled)
        save(frame/'targets.json.gz',targets)
        save(frame/'sampling_diagnostics.json',sampling_report)
        save(frame/'input_binding.json',dict(token=row['token'],image_paths=row['image_paths'],native_metadata=str(Path(paths['native_metadata'])/(row['token']+'.json.gz')) if not topdown_only else None,reference=ref))
        summary.append(dict(token=row['token'],counts=gt['counts'],capacity_passed=gt['capacity_passed'],actual_sampler_applied=gt['actual_sampler_applied']))
    save(out/'SUMMARY.json',dict(status='candidate_generated_pending_manual_review',version=VERSION,frames=summary,approved_for_training=False))
    return out
