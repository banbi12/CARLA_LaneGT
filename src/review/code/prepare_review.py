"""Build a new offline review workspace from a rendered baseline or raw extraction."""
from pathlib import Path
import argparse,copy,importlib.util,json,shutil,sys
REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src/postprocessing/code'))
from project import build_web,load,save,sha,link


def prepare(source,output):
    paths=load(REPO/'config/paths.local.json');source=source.resolve();output=output.absolute()
    if output.exists() or output.is_symlink():raise FileExistsError('Use a new output directory')
    for key in ['src','config','assets','archive','provenance','web']:
        protected=REPO/key
        if protected==output.resolve() or protected in output.resolve().parents:raise ValueError('Output inside source project component')
    for p in paths['protected_output_roots']:
        p=Path(p).resolve()
        if p==output.resolve() or p in output.resolve().parents:raise ValueError('Output inside protected input')
    output.mkdir(parents=True)
    if (source/'audit/data/index.js').exists():
        build_web(output,source)
    else:
        raw=load(source/'manifest.json');rows=copy.deepcopy(raw['frames'])
        known={r['token']:r for r in load(Path(paths['review60'])/'manifest/frames.json')} if (Path(paths['review60'])/'manifest/frames.json').exists() else {}
        for row in rows:row.setdefault('sample_split',known.get(row['token'],{}).get('sample_split','manual_selection'))
        (output/'frames').mkdir();(output/'geometry').mkdir()
        for row in rows:
            src=source/'frames'/row['token']
            shutil.copytree(src,output/'frames'/row['token'])
        for ref in {r['reference'] for r in rows}:shutil.copytree(source/'geometry'/ref,output/'geometry'/ref)
        link(output/'topdown_cases',Path(paths['topdown_root']))
        if any(r.get('image_paths') for r in rows):link(output/'native_images',Path(paths['native_images']))
        else:(output/'native_images').mkdir()
        save(output/'config/paths.json',paths);save(output/'manifest/frames.json',rows)
        sys.path.insert(0,str(REPO/'src/extraction/code'))
        spec=importlib.util.spec_from_file_location('local_review_renderer',REPO/'src/review/code/render_review.py')
        renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer);renderer.R=output
        for row in rows:renderer.render(row)
        index=[]
        for row in rows:
            c=load(output/'frames'/row['token']/'COMPLETE.json')
            index.append(dict(token=row['token'],scene=row['scene'],frame_idx=row['frame_idx'],weather=row['weather'],reference=row['reference'],sample_split=row['sample_split'],ready=True,counts=c['counts'],instances=c['instances'],actual_sampler_applied=c['actual_sampler_applied'],capacity_passed=c['capacity_passed'],sampling_warning_count=len(c['sampling_over_020m']),gt_sha256=c['gt_sha256']))
        ds=dict(dataset_id=output.name+'_LANEGT',version=raw['version'],manifest_sha256=sha(output/'manifest/frames.json'),frames=len(rows),ready=len(rows),native_images=sum(len(r.get('image_paths',{})) for r in rows),references=len({r['reference'] for r in rows}),classes=['divider','ped_crossing','boundary','centerline'],frames_index=index)
        ds['BEV_range_m']=load(output/'frames'/rows[0]['token']/'gt.json.gz')['BEV_range_m']
        build_web(output,output,dataset=ds)
    if not (output/'README.md').exists():shutil.copy2(REPO/'docs/POSTPROCESSING.md',output/'README.md')
    print(json.dumps(dict(passed=True,review=str(output),source=str(source),original_inputs_modified=False,GPU_used=False),ensure_ascii=False))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();prepare(args.source,args.output)
