"""Export/import CAD DXF with context, then reuse the CPU GT materializer."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,uuid,re
from project import load,save,sha,index,PACKAGE,DEFAULT_SOURCE
from edit_model import replay,targets_from_gt
from postprocess import validated_patch,materialize


def bridge(data):
    node=shutil.which('node')
    if not node:raise RuntimeError('CAD命令行需要Node.js 18+；浏览器导入导出无需Node.js')
    p=subprocess.run([node,str(PACKAGE/'code/cad_bridge.js')],input=json.dumps(data,ensure_ascii=False,allow_nan=False),text=True,capture_output=True)
    if p.returncode:raise ValueError(p.stderr.strip())
    return json.loads(p.stdout)


def frame(source,token,operations):
    ds=index(source);row=next((r for r in load(source/'manifest/frames.json') if r['token']==token),None)
    if row is None:raise ValueError('Unknown frame token')
    folder=source/'frames'/token;digest=sha(folder/'gt.json.gz')
    if next(f for f in ds['frames_index'] if f['token']==token)['gt_sha256']!=digest:raise ValueError('Source index/GT mismatch')
    gt=load(folder/'gt.json.gz');base=targets_from_gt(gt,[t['id'] for t in load(folder/'targets.json.gz')])
    return dict(dataset_id=ds['dataset_id'],manifest_sha256=ds['manifest_sha256'],token=token,
                base_gt_sha256=digest,model_from_world=row['transform'],BEV_range_m=gt.get('BEV_range_m',[-15,-30,15,30])),replay(base,operations,gt.get('BEV_range_m'))


def export(source,token,output,patch=None):
    operations=[]
    if patch:
        doc=load(patch);validated_patch(source,doc)
        operations=doc['frames'].get(token,{}).get('operations',[])
    meta,targets=frame(source,token,operations)
    data=bridge(dict(action='export',meta=meta,targets=targets,operations=operations,session_id='cad_'+uuid.uuid4().hex))
    if output.exists() or output.is_symlink():raise FileExistsError('CAD导出目录必须不存在')
    output.mkdir(parents=True)
    with (output/'drawing.dxf').open('w',encoding='utf-8',newline='') as stream:stream.write(data['dxf'])
    save(output/'context.json',data['context']);print(json.dumps(dict(passed=True,output=str(output),instances=len(targets)),ensure_ascii=False))


def import_dxf(source,dxf,context_path,patch_output,allow_empty=False,output=None):
    ctx=load(context_path);meta,targets=frame(source,ctx['token'],ctx['exported_operations'])
    if ctx.get('BEV_range_m',[-15,-30,15,30])!=meta['BEV_range_m']:raise ValueError('CAD BEV范围与源GT不一致')
    for k in ['dataset_id','manifest_sha256','base_gt_sha256']:
        if ctx.get(k)!=meta[k]:raise ValueError('CAD context/source mismatch: '+k)
    if len(ctx['targets'])!=len(targets):raise ValueError('CAD context target count differs')
    for a,b in zip(ctx['targets'],targets):
        if a['id']!=b['id'] or a['class_name']!=b['class_name'] or len(a['full_xyz'])!=len(b['full_xyz']) or any(abs(x-y)>1e-7 for p,q in zip(a['full_xyz'],b['full_xyz']) for x,y in zip(p,q)):
            raise ValueError('CAD context geometry differs from source/history')
    raw=dxf.read_bytes()
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        match=re.search(rb'ANSI_([0-9]+)',raw[:20000]);codec='cp'+match.group(1).decode('ascii') if match else 'cp1252'
        text=raw.decode(codec)
    data=bridge(dict(action='import',dxf=text,context=ctx,
        operation_id='cad_'+uuid.uuid4().hex,dxf_sha256=sha(dxf)))
    if data['summary']['empty'] and data['summary']['before']>0 and not allow_empty:raise ValueError('导回将清空全部可编辑几何；确认后使用--allow-empty')
    validated_patch(source,data['patch'])
    if patch_output.exists() or patch_output.is_symlink() or Path(str(patch_output)+'.report.json').exists():raise FileExistsError('补线JSON和报告输出必须不存在')
    save(patch_output,data['patch']);save(Path(str(patch_output)+'.report.json'),data['summary'])
    if output:materialize(source,patch_output,output)
    print(json.dumps(dict(passed=True,patch=str(patch_output),summary=data['summary']),ensure_ascii=False))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,default=DEFAULT_SOURCE)
    sub=ap.add_subparsers(dest='command',required=True)
    ex=sub.add_parser('export');ex.add_argument('--token',required=True);ex.add_argument('--directory',type=Path,required=True);ex.add_argument('--patch',type=Path)
    im=sub.add_parser('import');im.add_argument('--dxf',type=Path,required=True);im.add_argument('--context',type=Path,required=True);im.add_argument('--patch-output',type=Path,required=True);im.add_argument('--allow-empty',action='store_true');im.add_argument('--output',type=Path)
    args=ap.parse_args()
    if args.command=='export':export(args.source,args.token,args.directory,args.patch)
    else:import_dxf(args.source,args.dxf,args.context,args.patch_output,args.allow_empty,args.output)
