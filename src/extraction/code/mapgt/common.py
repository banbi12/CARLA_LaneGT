import hashlib
import json
from pathlib import Path


class InvalidGT(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise InvalidGT(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def file_ref(path):
    p = Path(path).resolve()
    return dict(path=str(p), sha256=sha(p))


def verify_ref(ref):
    p = Path(ref['path'])
    require(p.is_file(), 'SOURCE_FILE_MISSING: '+str(p))
    require(sha(p) == ref['sha256'], 'SOURCE_FILE_HASH: '+str(p))
    return p
