"""XODR-only：复用原版世界几何，以相同位姿、BEV、实际采样接口导出。"""
from pathlib import Path
import argparse,copy,json,os,re,subprocess,sys
import numpy as np
R=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(R/'src/xodr_only/code'),str(R/'src/extraction/code')]
from semgt.io import load,save,sha,selected_rows,fresh_output
from semgt.bev import bounds
from semgt.engine import assemble,clip_targets
from semgt.centerlines import local,clip_provided
from semgt.sampling import actual_targets,diagnostics
from xodrgt import VERSION
from xodrgt.world import validate

def main():
    os.environ['CUDA_VISIBLE_DEVICES']=''
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--paths',type=Path,default=R/'config/paths.local.json')
    choice=p.add_mutually_exclusive_group();choice.add_argument('--tokens',nargs='+');choice.add_argument('--selection',type=Path)
    p.add_argument('--limit',type=int);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--world',type=Path,help='已经生成的 XODR-only 世界缓存，省去 Shapely 2 环境')
    p.add_argument('--geometry-python',help='独立 Shapely 2 环境的 Python，仅用于生成世界缓存')
    p.add_argument('--xodr',type=Path,default=R/'assets/capture/server_Town10HD.xodr')
    p.add_argument('--lane-decisions',type=Path);p.add_argument('--boundary-decisions',type=Path)
    p.add_argument('--centerline',choices=['none','generate','provided'],default='none')
    p.add_argument('--bev-range',type=float,nargs=4,default=[-15,-30,15,30],metavar=('XMIN','YMIN','XMAX','YMAX'))
    p.add_argument('--topdown-only',action='store_true',help='不附带六相机输入；XODR 几何提取本身始终不读取顶视图')
    p.add_argument('--skip-sampler',action='store_true');p.add_argument('--sampler',choices=['none','maptr'],default='none');a=p.parse_args()
    if a.world and (a.lane_decisions or a.boundary_decisions or a.geometry_python or '--xodr' in sys.argv):p.error('--world 不能同时指定 XODR、生成环境或人工决定文件')
    paths=load(a.paths);tokens=a.tokens
    if a.selection:
        chosen=load(a.selection);chosen=chosen['frames'] if isinstance(chosen,dict) else chosen
        tokens=[r['token'] if isinstance(r,dict) else r for r in chosen]
    rows=copy.deepcopy(selected_rows(paths,tokens,a.limit));roi=bounds(a.bev_range)
    if len({r['token'] for r in rows})!=len(rows):raise ValueError('帧清单包含重复 token')
    partition=load(R/'config/extraction/boundary_partition_policy.json')
    for row in rows:
        for key in ['token','reference']:
            v=row[key]
            if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',v) or v in ['.','..']:raise ValueError('帧标识只接受字母、数字、下划线、点和短横线: '+key)
        clip_targets([],row['transform'],partition,roi)
        row['BEV_range_m']=roi
        if a.topdown_only:row['image_paths']={}
        else:row.setdefault('image_paths',{})
    expected=load(R/'config/resources.town10.json')['files']['capture/server_Town10HD.xodr']
    world=validate(load(a.world),expected) if a.world else None
    # Protect source code, all configured inputs, and explicitly supplied source files.
    protected=paths.get('protected_output_roots',[])+[str(R/k) for k in ['src','config','assets','web']]
    protected += [paths[k] for k in ['topdown_root','native_images','native_labels','native_metadata'] if paths.get(k)]
    protected += [paths['frame_manifest']]+[str(x) for x in [a.world,a.xodr,a.lane_decisions,a.boundary_decisions] if x]
    out=fresh_output(a.output,protected)
    if world is None:
        worker=[a.geometry_python or paths.get('xodr_python') or sys.executable,'-B',str(R/'tools/generate_xodr_world.py'),
                '--xodr',str(a.xodr),'--output',str(out/'world.json')]
        for name,value in [('--lane-decisions',a.lane_decisions),('--boundary-decisions',a.boundary_decisions)]:
            if value:worker += [name,str(value)]
        worker_env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='')
        worker_env.pop('LD_PRELOAD',None)  # The geometry interpreter has its own shared libraries.
        subprocess.run(worker,check=True,env=worker_env)
        world=validate(load(out/'world.json'),expected)
    else:save(out/'world.json',world)
    world_sha=sha(out/'world.json')
    save(out/'manifest.json',dict(version=VERSION,scheme='xodr-only',frames=rows,BEV_range_m=roi,
        xodr_sha256=expected,world_sha256=world_sha,centerline_mode=a.centerline,topdown_only=a.topdown_only,
        decision_files=world['decision_files'],semantic_images_used=False,GPU_used=False,candidate_only=True,approved_for_training=False))
    features=world['features'];completed=set();summary=[]
    for row in rows:
        ref=row['reference'];folder=out/'geometry'/ref
        if ref not in completed:
            save(folder/'candidates.json',features)
            save(folder/'audit.json',dict(scheme='xodr-only',semantic_images_used=False,small_gap_connections=[],
                double_yellow=[],rejected_connections=[],raw_observations=[],
                note='UI compatibility fields only; no semantic observations, pairing or gap repair executed.'))
            save(folder/'reference_manifest.json',dict(reference=ref,scheme='xodr-only',version=VERSION,
                xodr_sha256=expected,world_sha256=world_sha,topdown_used_for_geometry=False,
                decision_files=world['decision_files']))
            completed.add(ref)
        centers=[]
        if a.centerline=='generate':centers=local(world['centerlines'],row,roi)
        elif a.centerline=='provided':centers=clip_provided(load(Path(paths['native_labels'])/(row['token']+'.json.gz'))['classes']['centerline'],roi)
        gt,targets=assemble(row,features,centers,partition,bev_range=roi)
        sampled=None if a.skip_sampler or a.sampler=='none' else actual_targets(targets,paths['model_root'],roi)
        if sampled is not None:gt,targets=assemble(row,features,centers,partition,sampled,roi)
        report=diagnostics(targets,sampled) if sampled is not None else dict(status='not_run_diagnostic_only')
        gt.update(schema='maptrv2_xodr_gt_v1' if sampled is not None else 'lanegt_geometry_v1',algorithm_version=VERSION,scheme='xodr-only',xodr_sha256=expected,
            world_sha256=world_sha,decision_files=world['decision_files'],centerline_mode=a.centerline,
            centerline_exact_from_source=a.centerline=='provided' and roi==[-15.,-30.,15.,30.],
            semantic_images_used=False)
        frame=out/'frames'/row['token'];save(frame/'gt.json.gz',gt);save(frame/'targets.json.gz',targets)
        save(frame/'sampling_diagnostics.json',report)
        save(frame/'input_binding.json',dict(token=row['token'],image_paths=row['image_paths'],
            native_metadata=str(Path(paths['native_metadata'])/(row['token']+'.json.gz')) if row['image_paths'] else None,
            reference=ref,xodr_sha256=expected,world_sha256=world_sha))
        if sampled is not None:np.savez_compressed(frame/'actual_sampler_targets.npz',target_ids=np.asarray([f['id'] for f in targets]),**sampled)
        summary.append(dict(token=row['token'],counts=gt['counts'],capacity_passed=gt['capacity_passed']))
    save(out/'SUMMARY.json',dict(status='candidate_generated',scheme='xodr-only',frames=summary,approved_for_training=False,GPU_used=False))
    print(json.dumps(dict(passed=True,output=str(out),frames=len(rows),scheme='xodr-only',GPU_used=False),ensure_ascii=False))
if __name__=='__main__':main()
