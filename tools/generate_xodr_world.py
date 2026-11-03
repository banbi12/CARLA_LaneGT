#!/usr/bin/env python3
"""在独立 Shapely 2 环境复用旧版 XODR-only 世界几何流程。"""
from pathlib import Path
import argparse,json,os,sys
os.environ['CUDA_VISIBLE_DEVICES']=''
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R/'src/xodr_only/code'),str(R/'src/extraction/code')]
from semgt.io import save

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xodr',type=Path,default=R/'assets/capture/server_Town10HD.xodr')
    p.add_argument('--lane-decisions',type=Path);p.add_argument('--boundary-decisions',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists() or a.output.is_symlink():raise FileExistsError('输出文件必须不存在')
    try:
        from shapely import set_precision
    except ImportError as e:
        raise SystemExit('世界几何生成需要独立 Shapely 2 环境；请安装 requirements-xodr.txt，或对 xodr-only 指定 --geometry-python。不要覆盖现有 MapTRv2 环境。') from e
    from xodrgt.world import generate
    result=generate(R,a.xodr,a.lane_decisions,a.boundary_decisions);save(a.output,result)
    print(json.dumps(dict(passed=True,scheme='xodr-only',features=len(result['features']),output=str(a.output),GPU_used=False),ensure_ascii=False))
if __name__=='__main__':main()
