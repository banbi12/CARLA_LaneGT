"""Read-only audit of the public Git index; machine-local ignored files excluded."""
from pathlib import Path
import json,subprocess,hashlib
R=Path(__file__).resolve().parents[1]
names=subprocess.check_output(['git','ls-files','-z'],cwd=R).decode().split('\0')
errors=[];hashes={}
for name in filter(None,names):
 p=R/name
 if p.is_symlink():
  try:p.resolve().relative_to(R)
  except ValueError:errors.append('external symlink: '+name)
  continue
 data=p.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
 if p.name!='.gitkeep' and (name.startswith(('data/','outputs/','reports/','.local/','assets/maps/','assets/capture/')) or name.endswith(('.local.json','.pth','.pkl'))):errors.append('private/runtime file: '+name)
 if any(x in data for x in [b'/home/'+b'banbi/',b'/media/'+b'banbi/']):errors.append('machine path: '+name)
 if len(data)>2_000_000:errors.append('unexpected large file: '+name)
print(json.dumps(dict(passed=not errors,public_files=len(hashes),errors=errors),indent=2))
if errors:raise SystemExit(1)
