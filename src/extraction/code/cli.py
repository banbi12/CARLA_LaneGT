"""MapTRv2 collector V4. check/collect dry-run are CPU-only metadata operations."""
from pathlib import Path
import sys,argparse,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from semgt.io import load,save,selected_rows,sha,fresh_output

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--paths',default=str(ROOT/'config/paths.json'))
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ['check','collect','extract']:
        sub=subs.add_parser(name);selection=sub.add_mutually_exclusive_group();selection.add_argument('--tokens',nargs='+');selection.add_argument('--selection',help='JSON frame records or {frames:[...]} with token fields');sub.add_argument('--limit',type=int);sub.add_argument('--centerline',choices=['none','generate','provided'],default='none');sub.add_argument('--bev-range',nargs=4,type=float,metavar=('XMIN','YMIN','XMAX','YMAX'),default=[-15,-30,15,30]);sub.add_argument('--topdown-only',action='store_true');sub.add_argument('--centerline-world')
        if name!='check':sub.add_argument('--output')
        if name=='collect':sub.add_argument('--execute',action='store_true',help='explicitly start owned CARLA/GPU capture; default is metadata dry-run')
        if name=='extract':sub.add_argument('--hint-world');sub.add_argument('--skip-sampler',action='store_true');sub.add_argument('--sampler',choices=['none','maptr'],default='none')
    args=parser.parse_args(argv)
    if args.centerline_world and args.centerline!='generate':parser.error('--centerline-world需要--centerline generate')
    paths=load(args.paths);tokens=args.tokens
    if args.selection:
        chosen=load(args.selection);chosen=chosen['frames'] if isinstance(chosen,dict) else chosen;tokens=[r['token'] if isinstance(r,dict) else r for r in chosen]
    rows=selected_rows(paths,tokens,args.limit)
    if args.command=='check':
        import numpy as np
        from mapgt.world import flat_map_guard
        from semgt.geometry import validate_meta
        flat_map_guard(ROOT/'capture_template/evidence/server_Town10HD.xodr')
        crossings=load(ROOT/'source_geometry/xodr_crosswalk_world.json')
        if crossings['xodr_sha256']!=sha(ROOT/'capture_template/evidence/server_Town10HD.xodr'):raise ValueError('Map identity mismatch')
        from semgt.input_contract import cases as read_cases,validate
        cases=read_cases(paths)
        for row in rows:
            if not args.topdown_only and set(row['image_paths'])!={'CAM_FRONT','CAM_FRONT_LEFT','CAM_FRONT_RIGHT','CAM_BACK','CAM_BACK_LEFT','CAM_BACK_RIGHT'}:raise ValueError('Six native cameras are required')
            ref=Path(paths['topdown_root'])/row['reference']
            for name in ['COMPLETE.json','metadata.json','semantic_labels.png','rgb.png','depth_m.npy']:
                if not (ref/name).is_file():raise FileNotFoundError(ref/name)
            case=cases.get(row['reference']);meta=load(ref/'metadata.json');proof=load(ref/'COMPLETE.json')
            validate_meta(meta)
            if sha(ref/'metadata.json')!=proof['files']['metadata.json']:raise ValueError('Reference metadata hash mismatch')
            if meta['xodr_sha256']!=crossings['xodr_sha256']:raise ValueError('Reference map identity mismatch')
            validate(row,meta,case,crossings['xodr_sha256'])
            from semgt.bev import coverage
            coverage(meta,row['transform'],args.bev_range)
            for value in ([] if args.topdown_only else row['image_paths'].values()):
                if not Path(value).is_file():raise FileNotFoundError(value)
            for key in ([] if args.topdown_only else ['native_metadata'])+(['native_labels'] if args.centerline=='provided' else []):
                if not (Path(paths[key])/(row['token']+'.json.gz')).is_file():raise FileNotFoundError(row['token'])
        print(json.dumps(dict(passed=True,selected_frames=len(rows),unique_references=len({r['reference'] for r in rows}),reference_paths_present=True,calibration_and_exact_pose_binding=True,reference_metadata_hashes_verified=True,metadata_only=True,images_decoded=False,GT_extracted=False,GPU_started=False,CARLA_started=False)));return
    if args.command=='collect':
        from semgt.collection import planned,execute
        if not args.execute:
            plan=planned(ROOT,paths,rows)
            if args.output:
                protected=paths.get('protected_output_roots',[])+[paths['native_images'],paths['native_metadata'],paths['native_labels']]
                out=fresh_output(args.output,protected);save(out/'COLLECTION_DRY_RUN.json',plan)
            print(json.dumps(dict(status=plan['status'],source_frames=len(rows),exact_pose_cases=len(plan['exact_pose_cases']),GPU_started=False,CARLA_started=False)));return
        if not args.output:parser.error('--execute requires a new --output directory')
        print(execute(ROOT,paths,rows,args.output));return
    if not args.output:parser.error('extract requires a new --output directory')
    from semgt.runner import run
    from semgt.policy import checked
    hints=None
    if args.hint_world:
        try:hints=load(args.hint_world)
        except (OSError,ValueError):hints={'features':None}
    print(run(ROOT,paths,rows,args.output,checked(load(ROOT/'config/semantic_policy.json')),hints,args.sampler=='maptr' and not args.skip_sampler,args.centerline,args.bev_range,args.topdown_only,args.centerline_world))
if __name__=='__main__':main()
