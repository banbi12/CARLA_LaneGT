#!/usr/bin/env python3
"""按原版XODR车道几何、局部重叠去重与校验流程生成中心线。"""
from pathlib import Path
import argparse,json,sys
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'src/extraction/code'))
from mapgt.world import flat_map_guard
from semgt.io import save,sha
from semgt.legacy_centerline_pipeline import generate as legacy_generate,ENGINE

def generate(xodr,step):
    if not .05<=step<=2:raise ValueError('采样间隔应为0.05～2米')
    flat_map_guard(xodr)
    pin=json.loads((R/'config/resources.town10.json').read_text())['files']['capture/server_Town10HD.xodr']
    if sha(xodr)!=pin:raise ValueError('仅支持指纹匹配的Town10 XODR')
    result=legacy_generate(xodr,step)
    return dict(schema='lanegt_centerline_world_v2',generator=ENGINE,map_name='Town10HD',xodr_sha256=sha(xodr),sample_step_m=step,
        migration_provenance=json.loads((R/'config/extraction/legacy_centerline_provenance.json').read_text()),**result,
        representation='original directed lane sources, partial-overlap deduplicated geometry and audited topology; no invented connectors',
        GPU_used=False,CARLA_server_started=False,CARLA_API_used=False,human_review_required=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xodr',type=Path,default=R/'assets/capture/server_Town10HD.xodr')
    p.add_argument('--step-m',type=float,default=.5);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists() or a.output.is_symlink():raise FileExistsError('输出文件必须不存在')
    result=generate(a.xodr,a.step_m);save(a.output,result)
    print(json.dumps(dict(passed=True,generator=ENGINE,raw_lanes=len(result['raw_centerlines']),curves=len(result['features']),output=str(a.output),GPU_used=False,CARLA_API_used=False)))
if __name__=='__main__':main()
