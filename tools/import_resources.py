"""Import locally authorized matching Town10 resources; no network downloads."""
from pathlib import Path
import argparse,json,hashlib,shutil
R=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--from-directory',type=Path,required=True);a=p.parse_args()
manifest=json.loads((R/'config/resources.town10.json').read_text())['files']
for name,digest in manifest.items():
 source=a.from_directory/name
 if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise SystemExit('Wrong map/resource fingerprint: '+name)
for name,digest in manifest.items():
 target=R/'assets'/name;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise SystemExit('Refuse to overwrite differing resource: '+name)
 if not target.exists():shutil.copy2(a.from_directory/name,target)
print('Verified/imported',len(manifest),'ignored runtime resources')
