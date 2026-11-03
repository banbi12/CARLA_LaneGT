"""Version-pinned planar world source; centerline graph uses raw lane identities."""
import copy
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import numpy as np
from . import CLASSES
from .common import digest, load, require, sha


def flat_map_guard(path):
    root = ET.parse(path).getroot()
    require(all(len(r.findall('lanes/laneSection')) == 1 for r in root.findall('road')),
            'PHASE_A_SINGLE_SECTION_ONLY')
    for tag in ('elevationProfile/elevation','lateralProfile/superelevation','lateralProfile/crossfall'):
        for item in root.findall('road/'+tag):
            require(all(abs(float(item.get(k, '0'))) < 1e-9 for k in ('a','b','c','d')),
                    'PHASE_A_PLANAR_MAP_ONLY: '+tag)
    return dict(world_z_m=0., xodr_elevation_verified=True,
                scope='Flat same-hash Town10HD only; full measured 3D ego/camera transforms retained')


def checked_feature(f):
    require(f['class'] in CLASSES and bool(f['id']), 'FEATURE_CLASS_OR_ID')
    p = np.asarray(f['points_xyz'], dtype=float)
    require(p.ndim == 2 and p.shape[1] == 3 and len(p) >= 2 and np.isfinite(p).all(),
            'WORLD_GEOMETRY_FINITE_XYZ')
    require(np.max(np.abs(p[:,2])) < 1e-9, 'PHASE_A_PATCH_REQUIRES_Z_ZERO')
    require(np.linalg.norm(np.diff(p[:,:2], axis=0), axis=1).sum() > .05,
            'DEGENERATE_WORLD_GEOMETRY')
    require(isinstance(f['source'], dict) and bool(f['source']), 'WORLD_PROVENANCE')
    if f['class'] == 'centerline':
        require(all(k in f['source'] for k in ('road_id','section_s','lane_id','travel_s','source_refs')),
                'CENTERLINE_SOURCE_FIELDS')
        require(f['source']['travel_s'] in ('increasing','decreasing'), 'CENTERLINE_DIRECTION')
    return f


def from_legacy(path, xodr_path):
    w = load(path)
    require(w['map'] in ('Town10HD','Town10HD_Opt'), 'BASE_MAP_NAME')
    require(w['xodr_sha256'] == sha(xodr_path), 'BASE_XODR_HASH')
    plane = flat_map_guard(xodr_path)
    features = {}
    for cls, key in [('divider','dividers'),('ped_crossing','crosswalks'),('boundary','boundary_lines')]:
        for entry in w[key]:
            uid = cls+':'+digest(dict(source=entry['source'], geometry=entry['points']))[:24]
            f = dict(id=uid, **{'class':cls}, source=entry['source'],
                     points_xyz=[[float(p[0]),float(p[1]),0.] for p in entry['points']])
            require(uid not in features, 'DUPLICATE_SOURCE_FEATURE_ID')
            features[uid] = checked_feature(f)
    lane_keys = {}
    for entry in w['raw_centerlines']:
        uid = 'lane:'+entry['id']
        f = dict(id=uid, **{'class':'centerline'}, source=entry['source'],
                 points_xyz=[[float(p[0]),float(p[1]),0.] for p in entry['points']])
        features[uid] = checked_feature(f)
        s = f['source']; key = (s['road_id'],s['lane_id'])
        require(key not in lane_keys, 'MULTI_SECTION_GRAPH_NOT_SUPPORTED')
        lane_keys[key] = uid
    edges = {}
    for e in w['topology']['edges']:
        if e['status'] != 'accepted':
            continue
        e = copy.deepcopy(e)
        e['from'] = lane_keys[tuple(e['from'])]; e['to'] = lane_keys[tuple(e['to'])]
        e['id'] = 'edge:'+digest(e)[:24]
        edges[e['id']] = e
    result = dict(schema='mapgt_world_v2', source_map_name=w['map'],
        map_identity='Town10HD@'+w['xodr_sha256'], xodr_sha256=w['xodr_sha256'],
        base_world_sha256=sha(path), plane=plane, features=features, edges=edges,
        patch_receipts=[], candidate_only=True)
    check_graph(result)
    return result


def check_graph(world):
    for key, f in world['features'].items():
        require(key == f['id'], 'FEATURE_KEY_ID_MISMATCH')
        checked_feature(f)
    for key, e in world['edges'].items():
        require(key == e['id'] and e['from'] != e['to'], 'EDGE_ID_OR_SELF_LOOP')
        for node in (e['from'], e['to']):
            require(node in world['features'] and world['features'][node]['class'] == 'centerline',
                    'DANGLING_CENTERLINE_EDGE: '+node)
        start = np.asarray(world['features'][e['from']]['points_xyz'][-1])
        end = np.asarray(world['features'][e['to']]['points_xyz'][0])
        require(float(np.linalg.norm(start-end)) <= .5, 'EDGE_ENDPOINT_GAP_GT_0.5M: '+key)


def geometries(world, legacy_dir=None):
    """Regenerate deduped geometry from authoritative raw centerline features."""
    from semgt.legacy_centerlines import deduplicate_centerlines
    from shapely.geometry import LineString
    noncenter = [copy.deepcopy(f) for f in world['features'].values() if f['class'] != 'centerline']
    raw = [dict(id=f['id'], source=f['source'], points=[p[:2] for p in f['points_xyz']],
                length_m=round(LineString(f['points_xyz']).length,4))
           for f in world['features'].values() if f['class'] == 'centerline']
    require(bool(raw), 'EMPTY_CENTERLINE_WORLD')
    centers, stats = deduplicate_centerlines(raw)
    for f in centers:
        uid = 'center_geometry:'+digest(dict(source=f['source'],points=f['points']))[:24]
        noncenter.append(dict(id=uid, **{'class':'centerline'}, source=f['source'],
            points_xyz=[[float(p[0]),float(p[1]),0.] for p in f['points']]))
    return noncenter, stats
