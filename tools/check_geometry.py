"""Read-only generic GT validation; no model, Torch or simulator imports."""
from pathlib import Path
import argparse,json,sys
import numpy as np
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src/extraction/code'))
from semgt.io import load
from semgt.bev import bounds
def check(root):
    root=Path(root);rows=load(root/'manifest.json')['frames'] if (root/'manifest.json').exists() else load(root/'manifest/frames.json')
    seen=set();count=0
    for row in rows:
        token=row['token']
        if token in seen or Path(token).name!=token:raise ValueError('Invalid or repeated token')
        seen.add(token);gt=load(root/'frames'/token/'gt.json.gz');targets=load(root/'frames'/token/'targets.json.gz')
        if gt['token']!=token:raise ValueError('GT token differs')
        roi=bounds(gt.get('BEV_range_m'));lookup={}
        for cls,entries in gt['classes'].items():
            if cls not in ['divider','ped_crossing','boundary','centerline']:raise ValueError('Unknown class')
            for f in entries:
                if f['id'] in lookup:raise ValueError('Duplicate ID')
                p=np.asarray(f['render_xyz'],float);q=np.asarray(f['render_points'],float)
                if p.ndim!=2 or p.shape[1]!=3 or len(p)<2 or q.shape!=(len(p),2) or not np.isfinite(p).all() or not np.array_equal(p[:,:2],q):raise ValueError('Invalid finite XYZ/XY geometry')
                if np.any(p[:,:2]<np.array(roi[:2])-1e-6) or np.any(p[:,:2]>np.array(roi[2:])+1e-6):raise ValueError('Geometry outside BEV')
                lookup[f['id']]=(cls,f)
            if gt['counts'][cls]!=len(entries):raise ValueError('Counts mismatch')
        if len(targets)!=len(lookup) or {t['id'] for t in targets}!=set(lookup):raise ValueError('Target IDs mismatch')
        for t in targets:
            cls,f=lookup[t['id']]
            if cls!=t['class_name'] or f['render_xyz']!=t['full_xyz'] or f['render_points']!=t['full']:raise ValueError('Targets differ from GT')
        count+=len(targets)
    return dict(passed=True,frames=len(rows),instances=count,model_imported=False,metric='format_and_geometry_consistency_not_semantic_accuracy')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(check(a.root)))
