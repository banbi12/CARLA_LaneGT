"""Optional MapTRv2 adapter: copy generic geometry into a new sampled dataset."""
from pathlib import Path
import argparse,copy,json,shutil,sys
import numpy as np
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'src/extraction/code'),str(R/'tools')]
from semgt.io import load,save,sha,fresh_output
from semgt.sampling import actual_targets,diagnostics
from semgt.portable import finalize
from check_geometry import check
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    paths=load(R/'config/paths.local.json');source=a.source.resolve();check(source)
    if not paths.get('model_root'):raise ValueError('MapTR export requires model_root')
    if (source/'manifest.json').exists():manifest=load(source/'manifest.json');rows=manifest['frames']
    else:
        rows=load(source/'manifest/frames.json');manifest=dict(version=load(source/'frames'/rows[0]['token']/'gt.json.gz')['algorithm_version'],frames=rows)
    protected=[source]+[R/k for k in ['src','config','assets','web']]+[Path(x) for x in paths.get('protected_output_roots',[])]
    out=fresh_output(a.output,protected);receipts=[]
    for row in rows:
        token=row['token'];src=source/'frames'/token;dst=out/'frames'/token;dst.mkdir(parents=True)
        gt=load(src/'gt.json.gz');targets=load(src/'targets.json.gz');original=copy.deepcopy(targets)
        sampled=actual_targets(targets,paths['model_root'],gt['BEV_range_m']);report=diagnostics(targets,sampled)
        index={f['id']:i for i,f in enumerate(targets)}
        for cls,entries in gt['classes'].items():
            for f in entries:
                if cls!='centerline':f['points']=sampled['fixed20'][index[f['id']]].tolist()
        gt.update(actual_sampler_applied=True);finalize(gt,True)
        save(dst/'gt.json.gz',gt);save(dst/'targets.json.gz',targets);save(dst/'sampling_diagnostics.json',report)
        if (src/'input_binding.json').exists():shutil.copy2(src/'input_binding.json',dst/'input_binding.json')
        np.savez_compressed(dst/'actual_sampler_targets.npz',target_ids=np.asarray([f['id'] for f in targets]),**sampled)
        assert [(f['id'],f['full_xyz']) for f in targets]==[(f['id'],f['full_xyz']) for f in original]
        receipts.append(dict(token=token,source_gt_sha256=sha(src/'gt.json.gz')))
    for ref in {r['reference'] for r in rows}:shutil.copytree(source/'geometry'/ref,out/'geometry'/ref,symlinks=False)
    manifest['sampling_backend']='maptr';save(out/'manifest.json',manifest)
    save(out/'EXPORT.json',dict(adapter='maptrv2',sources=receipts,full_geometry_unchanged=True,approved_for_training=False))
    print(json.dumps(dict(passed=True,output=str(out),frames=len(rows))))
if __name__=='__main__':main()
