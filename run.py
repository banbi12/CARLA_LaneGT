#!/usr/bin/env python3
"""CARLA LaneGT：环境配置、GT 提取、审核及页面/CAD 人工处理。"""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent


def config():
    path=ROOT/'config/paths.local.json'
    if path.exists():return json.loads(path.read_text())
    raise SystemExit('Configure this checkout first: python3 tools/configure.py --from-json YOUR_PATHS.json')
def execute(script,args,model_env=True):
    paths=config();adapter=('--sampler' in args and args[args.index('--sampler')+1]=='maptr') or script.name in ['export_maptr.py','check_dataset.py']
    if adapter and (not paths.get('model_root') or not paths.get('maptr_python')):raise SystemExit('可选 MapTR 适配需要配置 model_root 和 maptr_python')
    python=paths['maptr_python'] if adapter else paths.get('runtime_python',sys.executable)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    if not ('collect' in args and '--execute' in args):env['CUDA_VISIBLE_DEVICES']=''
    if adapter:
        lib=Path(python).parent.parent/'lib/libstdc++.so.6'
        if lib.exists():env['LD_PRELOAD']=str(lib)
    return subprocess.call([python,'-B',str(script),*args],env=env,cwd=ROOT)


def main():
    if len(sys.argv)<2 or sys.argv[1] in ['-h','--help']:
        print(__doc__+'\n\n命令：\n  xodr-only              复用旧版 XODR-only 提取\n  compare                生成两方案同帧 BEV 对照\n  centerlines            从XODR离线生成可选中心线\n  doctor                 检查配置路径，不使用 GPU\n  check                  检查选定帧的提取输入\n  collect-plan           生成采集计划，不启动 CARLA/GPU\n  collect                采集顶视参考，需要显式 --execute\n  extract                通用完整几何 GT 提取\n  review                 生成新的审核及页面/CAD 编辑图册\n  postprocess            应用补线操作 JSON，生成新 GT\n  cad                    CAD DXF 导出与导回\n  export-maptr           可选导出 MapTRv2 实际采样\n  geometry-check         检查通用 GT 几何与实例绑定\n  dataset-check          检查新图册的 Dataset 和采样接口\n\n完整操作见 docs/QUICKSTART.md。');return 0
    command=sys.argv[1];args=sys.argv[2:];paths=config()
    if command=='xodr-only':return execute(ROOT/'src/xodr_only/code/cli.py',args)
    if command=='export-maptr':return execute(ROOT/'tools/export_maptr.py',args)
    if command=='geometry-check':return execute(ROOT/'tools/check_geometry.py',args)
    if command=='compare':return execute(ROOT/'tools/compare_schemes.py',args)
    if command=='centerlines':
        return execute(ROOT/'tools/generate_centerlines.py',args)
    if command=='doctor':
        ap=argparse.ArgumentParser();ap.add_argument('--topdown-only',action='store_true');ap.add_argument('--xodr-only',action='store_true');ap.add_argument('--centerline',choices=['none','generate','provided'],default='none');ap.add_argument('--capture',action='store_true');a=ap.parse_args(args)
        expected=['frame_manifest','runtime_python']
        if not a.xodr_only:expected+=['topdown_root']
        if a.capture:expected+=['cases']
        if not a.topdown_only:expected+=['native_metadata','native_images']
        if a.centerline=='provided':expected+=['native_labels']
        if a.capture:expected+=['carla_python']
        if a.capture:expected+=['carla_root']
        result={k:dict(path=paths[k],exists=Path(paths[k]).exists()) for k in expected}
        print(json.dumps(dict(project=str(ROOT),inputs=result,node=shutil.which('node'),GPU_started=False,CARLA_started=False),ensure_ascii=False,indent=2));return 0 if all(v['exists'] for v in result.values()) else 1
    if command in ['check','collect','collect-plan','extract']:
        if command=='collect-plan' and '--execute' in args:raise ValueError('collect-plan never starts CARLA; use collect --execute')
        return execute(ROOT/'src/extraction/code/cli.py',['--paths',str(ROOT/'config/paths.local.json'),'collect' if command=='collect-plan' else command,*args])
    if command=='review':
        ap=argparse.ArgumentParser();ap.add_argument('--source',default=paths['review60']);ap.add_argument('--output',default=str(ROOT/'outputs/review60'));a=ap.parse_args(args)
        return execute(ROOT/'src/review/code/prepare_review.py',['--source',a.source,'--output',a.output])
    if command in ['postprocess','cad']:return execute(ROOT/'src/postprocessing/code'/('postprocess.py' if command=='postprocess' else 'cad.py'),args)
    if command=='dataset-check':return execute(ROOT/'src/review/code/check_dataset.py',args)
    raise ValueError('Unknown command '+command)


if __name__=='__main__':raise SystemExit(main())
