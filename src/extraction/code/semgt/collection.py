"""Capture preparation is inert by default; CARLA imports live only in the child template."""
from pathlib import Path
import copy,shutil,subprocess,json
from .io import load,save,sha,fresh_output
from . import VERSION

def planned(project,paths,rows):
    if not paths.get('cases') or not Path(paths['cases']).is_file():raise ValueError('Capture planning requires explicit cases with measured camera placement')
    cases={c['case_id']:c for c in load(paths['cases'])};selected=[];seen=set()
    for row in rows:
        if row['reference'] in seen:continue
        case=copy.deepcopy(cases[row['reference']]);seen.add(row['reference'])
        if case['frame']['transform']!=row['transform']:
            raise ValueError('Capture must use exact full native pose, no nearest-pose substitution')
        selected.append(case)
    return dict(version=VERSION,status='dry_run_no_capture_started',source_rows=len(rows),exact_pose_cases=selected,
        quality='Epic',map='Town10HD_Opt',camera_reference=dict(height_m=60,size=[1152,2048],fov_deg=36,sensors=['RGB','SEMANTIC','DEPTH'],synchronized=True),
        six_cameras='optional supplied camera images and measured calibration; not required for topdown capture',
        layer_variant=load(project/'capture_template/config/layer_variants.json'),keep_layers=['Ground','Decals'],hide_confirmed_objects=len(load(project/'capture_template/evidence/selective_occluder_allowlist.json')),
        gpu_stop_MB_decimal=7400,gpu_trigger_MiB=7057,hot_map_switch=False,owned_server_only=True,
        annotation_contract=dict(divider='xodr_v41_base_with_semantic_supplement',old_divider_geometry='xodr_v41_base',crosswalk='XODR_objects',centerline='original_per_frame'),GPU_started=False,CARLA_started=False)

def execute(project,paths,rows,output):
    plan=planned(project,paths,rows)
    out=fresh_output(output,[Path(paths['frame_manifest']).parent,paths['native_images'],paths['native_metadata'],paths['native_labels']]+paths.get('protected_output_roots',[]))
    shutil.copytree(project/'capture_template',out,dirs_exist_ok=True)
    runtime_paths=load(out/'config/runtime_paths.json') if (out/'config/runtime_paths.json').exists() else dict(carla_root=paths.get('carla_root',''),carla_python=paths['carla_python']);runtime_paths.update(carla_python=paths['carla_python'],carla_root=paths.get('carla_root',runtime_paths['carla_root']));save(out/'config/runtime_paths.json',runtime_paths)
    for name in ['runtime','logs','tmp','cache','reports','topdown_cases']:(out/name).mkdir(exist_ok=True)
    save(out/'cases.json',plan['exact_pose_cases']);save(out/'COLLECTION_PLAN.json',plan)
    manifest=dict(version=VERSION,status='capture_prepared',map_identity_basis='user_confirmed_same_modified_CARLA_source_and_existing_current_XODR_match',annotation_contract=plan['annotation_contract'],approved_for_training=False,capture_execution_requested=True)
    save(out/'RUN_MANIFEST.json',manifest)
    # No world is loaded, client created, NVML queried or subprocess started before this explicit call.
    try:
        subprocess.run([paths['carla_python'],'-B','-u',str(out/'code/run_topdown.py'),'--stage','selective'],check=True)
        manifest['status']='capture_completed'
    except BaseException as error:
        manifest.update(status='capture_failed_or_interrupted',error=repr(error));save(out/'RUN_MANIFEST.json',manifest);raise
    save(out/'RUN_MANIFEST.json',manifest)
    return out
