"""Source-neutral topdown binding with explicit legacy metadata compatibility."""
from pathlib import Path
import numpy as np
from .io import load

def source_token(meta):
    current=meta.get('source_frame_token');legacy=meta.get('nuCarla_frame')
    if current is not None and legacy is not None and current!=legacy:raise ValueError('source_frame_token conflicts with legacy nuCarla_frame')
    token=current if current is not None else legacy
    if not isinstance(token,str) or not token:raise ValueError('Missing source_frame_token')
    return token

def cases(paths):
    p=Path(paths.get('cases',''))
    if not p.is_file():return {}
    result={}
    for c in load(p):
        if c['case_id'] in result:raise ValueError('Duplicate reference case_id')
        result[c['case_id']]=c
    return result

def validate(row,meta,case=None,expected_map=None):
    token=source_token(meta)
    if expected_map is not None and meta.get('xodr_sha256')!=expected_map:raise ValueError('Topdown/map identity differs')
    if meta.get('case_id',row['reference'])!=row['reference']:raise ValueError('Topdown case_id differs')
    transform=np.asarray(row['transform'],float)
    if transform.shape!=(4,4) or not np.isfinite(transform).all() or not np.allclose(transform[3],[0,0,0,1]) or not np.allclose(transform[:3,:3].T@transform[:3,:3],np.eye(3),atol=1e-5):raise ValueError('Full rigid BEV-from-world transform required')
    if case is not None:
        if case['case_id']!=row['reference'] or token!=case['frame']['token'] or not np.array_equal(case['frame']['transform'],transform):raise ValueError('Reference/representative frame binding differs')
    elif token!=row['token']:raise ValueError('Without cases, source_frame_token must equal frame token')
    measured=meta.get('GT_model_from_world')
    if measured is None and 'source_frame_token' in meta:raise ValueError('Generic topdown metadata requires GT_model_from_world')
    if measured is not None and not np.array_equal(np.asarray(measured,float),transform):raise ValueError('Measured topdown/BEV pose differs')
    # New datasets must provide synchronization evidence. Legacy captures already use these fields.
    ids=meta.get('sensor_frame_ids');times=meta.get('sensor_timestamps')
    if 'source_frame_token' in meta or ids is not None or times is not None:
        required={'RGB','SEMANTIC','DEPTH'}
        if not isinstance(ids,dict) or not isinstance(times,dict) or not required<=set(ids) or not required<=set(times):raise ValueError('RGB/SEMANTIC/DEPTH synchronization evidence required')
        frames=[ids[k] for k in sorted(required)];timestamps=np.asarray([times[k] for k in sorted(required)],float)
        if any(type(f) is not int or f<0 for f in frames) or len(set(frames))!=1 or not np.isfinite(timestamps).all() or np.ptp(timestamps)>1e-6:raise ValueError('Topdown sensors are not synchronized')
    return True
