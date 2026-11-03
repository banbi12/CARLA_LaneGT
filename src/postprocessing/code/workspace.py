"""Resolve source code/assets inside this project; data and model installations stay explicit."""
from pathlib import Path
import json

def settings(package,source=None):
    package=Path(package);cfg={}
    for p in [package/'project.json',Path(source)/'project.json' if source else None]:
        if p is not None and p.exists():cfg.update(json.loads(p.read_text()))
    repo=next((p for p in [package,*package.parents] if (p/'PROJECT_LAYOUT.json').is_file()),None)
    if repo is None and cfg.get('repository_root'):repo=Path(cfg['repository_root'])
    if repo is None or not (repo/'PROJECT_LAYOUT.json').is_file():raise ValueError('Cannot locate CARLA_LaneGT source project')
    paths=repo/'config/paths.local.json'
    if not paths.exists():paths=repo/'config/paths.example.json'
    cfg.update(repository_root=str(repo),paths_file=str(paths),extractor_code=str(repo/'src/extraction/code'),
               review_code=str(repo/'src/review/code'),audit_assets=str(repo/'web/audit'))
    local=json.loads((paths if paths.exists() else repo/'config/paths.example.json').read_text())
    cfg.setdefault('base_review',local['review60']);cfg.setdefault('canonical_review',local['review60'])
    cfg['metadata_root']=local.get('camera_metadata',local.get('native_metadata'));cfg['model_root']=local.get('model_root')
    return cfg
