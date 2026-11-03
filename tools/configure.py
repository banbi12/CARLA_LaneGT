"""创建独立于公开参数的运行环境配置，不修改源数据。"""
from pathlib import Path
import argparse,json,sys
R=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--from-json',type=Path,required=True);p.add_argument('--xodr-only',action='store_true',help='仅配置 XODR-only 几何提取，顶视 cases/root 可省略');a=p.parse_args()
d=json.loads(a.from_json.read_text());target=R/'config/paths.local.json'
if target.exists():raise SystemExit('配置文件已存在，请明确编辑而不是覆盖')
required=['frame_manifest','data_root']
if not a.xodr_only:required+=['topdown_root']
for public,legacy in [('camera_metadata','native_metadata'),('camera_images','native_images'),('centerline_labels','native_labels')]:
    if d.get(public) and d.get(legacy) and d[public]!=d[legacy]:raise SystemExit('配置别名冲突: '+public+'/'+legacy)
    if d.get(public):d[legacy]=d[public]
missing=[k for k in required if not d.get(k)]
if missing:raise SystemExit('缺少配置字段: '+str(missing))
for key in ['native_metadata','native_labels','native_images','carla_root','cases']+(['cases','topdown_root'] if a.xodr_only else []):
    if not d.get(key):d[key]=str(R/'data/not_configured'/key)
d.setdefault('runtime_python',sys.executable)
if not d.get('carla_python'):d['carla_python']=sys.executable
if not d.get('review60'):d['review60']=str(R/'outputs/review1')
if not d.get('previous_editor'):d['previous_editor']=d['review60']
d.update(project_root=str(R),dataset_adapter_root=str(R/'src/adapters'))
protected=d.get('protected_output_roots',[])+[str(R/k) for k in ['src','config','assets','web']]
protected += [d[k] for k in ['topdown_root','native_metadata','native_labels','native_images']]
d['protected_output_roots']=sorted(set(protected));target.write_text(json.dumps(d,indent=2)+'\n')
print(target)
