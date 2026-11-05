#!/usr/bin/env python3
"""只读比较同帧 XODR-only 与 semantic 结果，生成独立 BEV 对照页。"""
from pathlib import Path
import argparse,html,json,re,sys
import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R/'src/extraction/code'),str(R/'src/review/code')]
from semgt.io import load,save,fresh_output
from semgt.bev import bounds
from render_review import bev

def rows(root):
    p=root/'manifest.json'
    data=load(p)['frames'] if p.exists() else load(root/'manifest/frames.json')
    return {r['token']:r for r in data}

def map_sha(root,row,gt):
    if gt.get('xodr_sha256'):return gt['xodr_sha256']
    m=load(root/'geometry'/row['reference']/'reference_manifest.json')
    value=m.get('xodr_sha256') or m.get('xodr_connection_constraints',{}).get('xodr_sha256')
    if not value:raise ValueError('缺少地图指纹，不能确认两方案使用同一地图')
    return value

def metrics(a,b,tolerance):
    def lines(items):return [LineString(f['full']) for f in items]
    aa,bb=lines(a),lines(b);ua=unary_union(aa);ub=unary_union(bb)
    la=sum(x.length for x in aa);lb=sum(x.length for x in bb)
    return dict(xodr_instances=len(a),semantic_instances=len(b),xodr_length_m=float(la),semantic_length_m=float(lb),
        xodr_length_near_semantic_fraction=float(sum(x.intersection(ub.buffer(tolerance)).length for x in aa)/la) if la else None,
        semantic_length_near_xodr_fraction=float(sum(x.intersection(ua.buffer(tolerance)).length for x in bb)/lb) if lb else None)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xodr',type=Path,required=True);p.add_argument('--semantic',type=Path,required=True)
    p.add_argument('--tokens',nargs='+');p.add_argument('--tolerance-m',type=float,default=.20);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not np.isfinite(a.tolerance_m) or a.tolerance_m<=0:p.error('tolerance 必须为有限正数')
    a.xodr=a.xodr.resolve();a.semantic=a.semantic.resolve();xr=rows(a.xodr);sr=rows(a.semantic)
    tokens=a.tokens or sorted(set(xr)&set(sr))
    if not tokens or len(tokens)!=len(set(tokens)) or any(t not in xr or t not in sr for t in tokens):raise ValueError('必须选择两方案共有且不重复的 token')
    prepared=[]
    for t in tokens:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',t) or t in ['.','..']:raise ValueError('无效 token')
        x,s=xr[t],sr[t];xg=load(a.xodr/'frames'/t/'gt.json.gz');sg=load(a.semantic/'frames'/t/'gt.json.gz')
        if xg.get('scheme')!='xodr-only' or sg.get('algorithm_version') not in ('semantic_v4_2_b_xodr_v41_base','semantic_primary_v4_3_xodr_v41_connection_path'):raise ValueError('输入必须依次为 XODR-only 与 V4.2 B/V4.3 semantic 方案')
        if not np.array_equal(x['transform'],s['transform']) or x['reference']!=s['reference']:raise ValueError('位姿或参考绑定不同，禁止混帧比较')
        if x.get('image_paths',{})!=s.get('image_paths',{}):raise ValueError('相机绑定不同；请对两方案采用相同的六相机/纯顶视模式')
        if bounds(xg.get('BEV_range_m'))!=bounds(sg.get('BEV_range_m')):raise ValueError('BEV 范围不同')
        if xg.get('centerline_mode')!=sg.get('centerline_mode'):raise ValueError('中心线模式不同，请使用相同 none/generate/provided 设置')
        if map_sha(a.xodr,x,xg)!=map_sha(a.semantic,s,sg):raise ValueError('两方案地图指纹不同')
        xt=load(a.xodr/'frames'/t/'targets.json.gz');st=load(a.semantic/'frames'/t/'targets.json.gz')
        prepared.append((t,x,xg,sg,xt,st))
    # Validate all pairs before creating output. The inputs are never rendered into or rewritten.
    protected=[a.xodr,a.semantic]+[R/k for k in ['src','web','config','assets']]
    cfg=R/'config/paths.local.json'
    if cfg.exists():protected+=load(cfg).get('protected_output_roots',[])
    out=fresh_output(a.output,protected);sections=[];report=[]
    for t,row,xg,sg,xt,st in prepared:
        (out/'images').mkdir(exist_ok=True)
        for label,targets in [('xodr',xt),('semantic',st)]:bev(targets,'full',xg['BEV_range_m']).save(out/'images'/(t+'_'+label+'.png'))
        classes={c:metrics([f for f in xt if f['class_name']==c],[f for f in st if f['class_name']==c],a.tolerance_m)
                 for c in ['divider','ped_crossing','boundary','centerline']}
        report.append(dict(token=t,scene=row['scene'],frame_idx=row['frame_idx'],BEV_range_m=xg['BEV_range_m'],metrics=classes))
        table=''.join('<tr><td>'+c+'</td><td>'+str(m['xodr_instances'])+'</td><td>'+str(m['semantic_instances'])+'</td><td>'+f"{m['xodr_length_m']:.2f}"+'</td><td>'+f"{m['semantic_length_m']:.2f}"+'</td></tr>' for c,m in classes.items())
        title=html.escape(str(row['scene'])+'/'+str(row['frame_idx']))
        sections.append(f'<section><h2>{title}</h2><code>{html.escape(t)}</code><div class="pair"><figure><figcaption>XODR-only</figcaption><img src="images/{t}_xodr.png"></figure><figure><figcaption>semantic + XODR 辅助</figcaption><img src="images/{t}_semantic.png"></figure></div><table><tr><th>类别</th><th>XODR 数量</th><th>semantic 数量</th><th>XODR 长度 / 米</th><th>semantic 长度 / 米</th></tr>{table}</table></section>')
    save(out/'comparison.json',dict(schema='lanegt_scheme_comparison_v1',xodr=str(a.xodr),semantic=str(a.semantic),
        frames=report,tolerance_m=a.tolerance_m,metric_scope='geometry difference only, not AP or accuracy; neither scheme is an independent truth',
        inputs_modified=False,GPU_used=False))
    text='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>LaneGT 两方案对照</title><style>body{font:16px sans-serif;background:#101820;color:#eee;margin:24px}section{border-top:1px solid #888;padding:20px 0}.pair{display:flex;gap:16px}figure{margin:12px 0;width:50%}img{width:100%;max-width:660px}td,th{padding:8px;border:1px solid #777}table{border-collapse:collapse}a{color:#7cf}</style><h1>XODR-only / semantic 同帧对照</h1><p>两侧采用同一地图、完整位姿、相机绑定、BEV 范围与中心线模式。浅蓝 divider，黄 boundary，紫 ped_crossing，绿 centerline。完整几何直接对比，不按采样误差择优。</p><p>几何差异不等于标注精度；请结合原图和各方案图册人工审核。<a href="comparison.json">导出对比统计 JSON</a></p>'
    (out/'gallery.html').write_text(text+'\n'.join(sections)+'</html>')
    print(json.dumps(dict(passed=True,frames=len(prepared),output=str(out),inputs_modified=False),ensure_ascii=False))
if __name__=='__main__':main()
