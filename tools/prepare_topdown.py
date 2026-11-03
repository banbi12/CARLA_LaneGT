#!/usr/bin/env python3
"""从通用顶视参考目录生成帧清单和路径配置草稿，不采集或改变图像。"""
from pathlib import Path
import argparse,sys
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src/extraction/code'))
from semgt.io import load,save,sha,fresh_output
from semgt.input_contract import source_token,validate
from semgt.geometry import validate_meta
from semgt.bev import coverage

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--topdown-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--bev-range',type=float,nargs=4,default=[-15,-30,15,30]);a=p.parse_args()
    root=a.topdown_root.resolve();rows=[];seen=set();expected=load(R/'config/resources.town10.json')['files']['capture/server_Town10HD.xodr']
    for path in sorted(root.glob('*/metadata.json')):
        meta=load(path);token=source_token(meta)
        if Path(token).name!=token or token in ['.','..'] or token in seen:raise ValueError('Invalid or repeated source token')
        seen.add(token)
        if 'GT_model_from_world' not in meta:raise ValueError('Metadata must contain GT_model_from_world')
        row=dict(token=token,reference=path.parent.name,transform=meta['GT_model_from_world'],scene=meta.get('scene','topdown'),frame_idx=meta.get('frame_idx',len(rows)),weather=meta.get('weather','unspecified'),image_paths={})
        validate(row,meta,expected_map=expected);validate_meta(meta);coverage(meta,row['transform'],a.bev_range)
        proof=load(path.parent/'COMPLETE.json')
        for name in ['rgb.png','semantic_labels.png','depth_m.npy','metadata.json']:
            if proof.get('files',{}).get(name)!=sha(path.parent/name):raise ValueError('COMPLETE hash missing or differs: '+name)
        rows.append(row)
    if not rows:raise ValueError('No topdown references found')
    out=fresh_output(a.output,[root,R/'src',R/'assets',R/'config',R/'web'])
    save(out/'frames.json',rows);save(out/'paths.json',dict(frame_manifest=str(out/'frames.json'),topdown_root=str(root),data_root=str(out.parent),runtime_python=sys.executable))
    print('Prepared',len(rows),'frames:',out/'paths.json')
if __name__=='__main__':main()
