import gzip,json,hashlib
from pathlib import Path

def load(path):
    path=Path(path)
    if path.suffix=='.gz':
        with gzip.open(path,'rt') as f:return json.load(f)
    return json.loads(path.read_text())

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    def serialize(x):
        if hasattr(x,'tolist'):return x.tolist()
        if hasattr(x,'item'):return x.item()
        raise TypeError(type(x).__name__)
    text=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=serialize)
    temporary=path.with_name(path.name+'.writing')
    if path.suffix=='.gz':
        with gzip.open(temporary,'wt') as f:f.write(text)
    else:temporary.write_text(text)
    temporary.replace(path)

def selected_rows(paths,tokens=None,limit=None):
    rows=load(paths['frame_manifest']);wanted=set(tokens or [])
    if wanted:
        rows=[r for r in rows if r['token'] in wanted]
        missing=wanted-{r['token'] for r in rows}
        if missing:raise ValueError('Unknown tokens: '+str(sorted(missing)))
    elif limit is None:
        raise ValueError('Explicit --tokens or --limit is required; no implicit full-dataset operation')
    if limit is not None:
        if limit<1:raise ValueError('limit must be positive')
        rows=rows[:limit]
    if not rows:raise ValueError('No frames selected')
    return rows

def fresh_output(path,protected):
    path=Path(path).expanduser().absolute()
    for root in protected:
        root=Path(root).resolve()
        try:path.resolve().relative_to(root)
        except ValueError:continue
        raise ValueError('Output must not be inside protected input: '+str(root))
    if path.exists() or path.is_symlink():raise FileExistsError('Refuse to overwrite an existing output: '+str(path))
    path.mkdir(parents=True,exist_ok=False)
    return path
