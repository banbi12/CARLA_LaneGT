"""Render actual V4 targets and build per-frame data for the existing isolated audit UI."""
from pathlib import Path
import json,gzip,hashlib,sys,time,collections
import numpy as np
from PIL import Image,ImageDraw

REPO=Path(__file__).resolve().parents[3];sys.path.insert(0,str(REPO/'src/extraction/code'))
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'code'))
from semgt.geometry import project,transform
from semgt.io import load,save,sha
from semgt.sampling import diagnostics
from semgt.bev import bounds,display,ring

COL=dict(divider='#44baff',ped_crossing='#ff6ddc',boundary='#ffd34e',centerline='#67dc93',auxiliary='#ff963b',unresolved='#ff5252')
CAMS=['CAM_FRONT_LEFT','CAM_FRONT','CAM_FRONT_RIGHT','CAM_BACK_LEFT','CAM_BACK','CAM_BACK_RIGHT']
NATIVE_FROM_MAP=np.array([[0,1,0,0],[-1,0,0,0],[0,0,1,0],[0,0,0,1]])

def line_on_camera(dr,points,t,k,color):
    pp=transform(points,t)
    for a,b in zip(pp,pp[1:]):
        if max(a[2],b[2])<.5:continue
        if a[2]<.5:a=a+(b-a)*((.5-a[2])/(b[2]-a[2]))
        if b[2]<.5:b=b+(a-b)*((.5-b[2])/(a[2]-b[2]))
        u=k@a;v=k@b;uv=np.array([u[:2]/u[2],v[:2]/v[2]])
        if np.isfinite(uv).all() and np.abs(uv).max()<1e7:dr.line([tuple(x) for x in uv],fill=color,width=3)

def bev(targets,kind='full',bev_range=None):
    im=Image.new('RGB',(660,1260),'#101820');dr=ImageDraw.Draw(im)
    a,b,c,d=bounds(bev_range);scale,cx,cy=display(bev_range)
    def uv(p):p=np.asarray(p);return np.c_[330+(p[:,0]-cx)*scale,630-(p[:,1]-cy)*scale]
    for x in np.arange(np.ceil(a/5)*5,c+.001,5):dr.line([tuple(uv([[x,b]])[0]),tuple(uv([[x,d]])[0])],fill='#30414e')
    for y in np.arange(np.ceil(b/5)*5,d+.001,5):dr.line([tuple(uv([[a,y]])[0]),tuple(uv([[c,y]])[0])],fill='#30414e')
    for f in targets:
        p=uv(f[kind]);dr.line([tuple(q) for q in p],fill=COL[f['class_name']],width=3)
        if kind!='full':
            for x,y in p:dr.ellipse((x-2,y-2,x+2,y+2),fill=COL[f['class_name']])
    if a<=0<=c and b<=0<=d:
        x,y=uv([[0,0]])[0];dr.polygon([(x,y-15),(x-7,y+4),(x+7,y+4)],fill='white')
    dr.text((40,8),str(c-a)+'m x '+str(d-b)+'m / forward UP / '+kind,fill='white')
    return im

def install_split(split):
    output=R/'iterations'/split
    for category in ['frames','geometry']:
        (R/category).mkdir(exist_ok=True)
        for folder in (output/category).iterdir():
            dest=R/category/folder.name
            if dest.is_symlink() and dest.resolve()!=folder.resolve():
                dest.resolve().relative_to(R/'iterations')
                replacement=dest.with_name(dest.name+'.next');replacement.symlink_to(Path('../iterations')/split/category/folder.name,target_is_directory=True);replacement.replace(dest)
            elif dest.is_symlink():assert dest.resolve()==folder.resolve()
            elif dest.exists():raise FileExistsError(dest)
            else:dest.symlink_to(Path('../iterations')/split/category/folder.name,target_is_directory=True)

def render(row):
    token=row['token'];out=R/'frames'/token;cid=row['reference'];folder=R/'geometry'/cid
    for writable in [out,folder]:
        if R.resolve() not in writable.resolve().parents:raise ValueError('Rendering requires owned frame/geometry copies, not linked original inputs: '+str(writable))
    targets=load(out/'targets.json.gz');gt=load(out/'gt.json.gz')
    has_sampler=bool(gt.get('actual_sampler_applied'))
    if has_sampler:
        with np.load(out/'actual_sampler_targets.npz') as sampled:
            assert sampled['target_ids'].tolist()==[t['id'] for t in targets]
            report=diagnostics(targets,sampled)
    else:
        report=dict(max_sampling_hd_m=None,over_020m=[])
        for f in targets:
            for k in ['fixed','worst','sampling_hd_m']:f.pop(k,None)
    save(out/'targets.json.gz',targets)
    payload=dict(actual_sampler_applied=has_sampler,frame=row,targets=targets,counts=gt['counts'],geometry_sha256=sha(folder/'candidates.json'),gt_sha256=sha(out/'gt.json.gz'),human_review='pending')
    (out/'audit_data.js').write_text('window.receiveFrame('+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+');')
    paths=load(R/'config/paths.json');has_cameras=bool(row.get('image_paths'))
    meta=load(Path(paths['native_metadata'])/(token+'.json.gz')) if has_cameras else {}
    raw=Image.new('RGB',(1920,768),'#101820');cams=raw.copy()
    for i,name in enumerate(CAMS if has_cameras else []):
        c=meta['cameras'][name]
        with Image.open(c['image_path']) as source:im=source.convert('RGB')
        raw.paste(im.resize((640,360)),(i%3*640,i//3*384+24));ImageDraw.Draw(raw).text((i%3*640+5,i//3*384+4),name,fill='white')
        dr=ImageDraw.Draw(im);tm=np.linalg.inv(np.array(c['optical_to_native']))@NATIVE_FROM_MAP;k=np.array(c['intrinsic'])
        for f in targets:line_on_camera(dr,f['full_xyz'],tm,k,COL[f['class_name']])
        cams.paste(im.resize((640,360)),(i%3*640,i//3*384+24));ImageDraw.Draw(cams).text((i%3*640+5,i//3*384+4),name,fill='white')
    if not has_cameras:
        ImageDraw.Draw(raw).text((40,40),'Topdown-only dataset: six-camera inputs are not provided',fill='white')
        cams=raw.copy()
    raw.save(out/'six_camera_raw.jpg',quality=90);cams.save(out/'six_camera_gt.jpg',quality=91)
    ref=R/'topdown_cases'/cid;m=load(ref/'metadata.json')
    if (ref/'semantic_palette.png').is_file():
        with Image.open(ref/'semantic_palette.png') as preview:preview.convert('RGB').save(out/'semantic_preview.png')
    elif (ref/'semantic_labels.png').is_file():
        ids=np.asarray(Image.open(ref/'semantic_labels.png'));lut=np.zeros((256,3),np.uint8);lut[1]=[128,64,128];lut[2]=[244,35,232];lut[24]=[157,234,50]
        Image.fromarray(lut[ids]).save(out/'semantic_preview.png')
    else:
        preview=Image.new('RGB',(640,360),'#101820');ImageDraw.Draw(preview).text((20,20),'Semantic input not supplied (XODR-only)',fill='white');preview.save(out/'semantic_preview.png')
    with Image.open(ref/'rgb.png') as source:rgb=source.convert('RGB')
    dr=ImageDraw.Draw(rgb);inv=np.linalg.inv(np.array(row['transform']));roundtrip=0.
    for f in targets:
        xyz=transform(f['full_xyz'],inv);uv=project(xyz,m);dr.line([tuple(q) for q in uv],fill=COL[f['class_name']],width=3)
        again=transform(xyz,row['transform']);roundtrip=max(roundtrip,float(np.abs(again-np.array(f['full_xyz'])).max()))
    from semgt.bev import coverage
    region=gt.get('BEV_range_m');corners=np.asarray(coverage(m,row['transform'],region)['ground_corners_world']);uv=project(corners,m)
    dr.line([tuple(q) for q in uv],fill='white',width=2);rgb.save(out/'topdown_gt.jpg',quality=92)
    for kind,name in ([('full','bev_gt.png'),('fixed','bev_fixed20.png'),('worst','bev_shift_v2_worst.png')] if has_sampler else [('full','bev_gt.png')]):bev(targets,kind,gt.get('BEV_range_m')).save(out/name)
    features=load(folder/'candidates.json');audit=load(folder/'audit.json')
    with Image.open(ref/'rgb.png') as source:context=source.convert('RGB')
    dr=ImageDraw.Draw(context)
    for f in features:
        uv=project(f['points_xyz'],m);dr.line([tuple(q) for q in uv],fill=COL.get(f['class_name'],'#ff5252'),width=3)
    context.save(folder/'evidence_overlay.jpg',quality=91)
    for key,name in [('small_gap_connections','small_gap_connections.json'),('double_yellow','double_yellow_audit.json'),('rejected_connections','rejected_connections.json')]:save(folder/name,audit[key])
    save(folder/'excluded_stoplines.json',dict(old_map_deletion_enabled=False,note='No silent deletion. Stop/symbol candidates remain in raw_observations with pending reasons.',observations=[f for f in audit['raw_observations'] if f['class_name']!='divider']))
    stats=dict(token=token,reference=cid,status='complete',counts=gt['counts'],instances=len(targets),capacity_passed=gt['capacity_passed'],max_sampling_hd_m=report['max_sampling_hd_m'],
        sampling_over_020m=report['over_020m'],centerline_exact=gt.get('centerline_exact_from_source',False),BEV_range_m=gt.get('BEV_range_m'),coordinate_roundtrip_max_m=roundtrip,gt_sha256=sha(out/'gt.json.gz'),actual_sampler_applied=gt['actual_sampler_applied'])
    assert roundtrip<1e-8
    save(out/'COMPLETE.json',stats)
    print('RENDERED',row['scene'],row['frame_idx'],len(targets),flush=True)

def main():
    import argparse
    global R
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True,type=Path);ap.add_argument('--split',required=True);ap.add_argument('--selection',required=True);a=ap.parse_args()
    R=a.root
    install_split(a.split)
    for row in load(a.selection):render(row)
if __name__=='__main__':main()
