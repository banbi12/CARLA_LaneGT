import json, hashlib
import numpy as np
from shapely.geometry import LineString
from scipy.interpolate import CubicHermiteSpline
from skimage.morphology import skeletonize

def transform(points, matrix):
    p = np.asarray(points, float)
    return (np.c_[p, np.ones(len(p))] @ np.asarray(matrix, float).T)[:, :3]

def validate_meta(meta):
    k = np.asarray(meta['intrinsic'], float)
    t = np.asarray(meta['optical_to_world_carla'], float)
    if k.shape != (3, 3) or t.shape != (4, 4) or not np.isfinite(k).all() or not np.isfinite(t).all():
        raise ValueError('Finite measured camera matrices are required')
    if min(k[0, 0], k[1, 1]) <= 0 or abs(np.linalg.det(t[:3, :3])) < .999:
        raise ValueError('Invalid camera calibration')
    if not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-5):
        raise ValueError('Camera transform must be rigid')
    if t[2, 2] > -.999 or t[2, 3] <= 0 or not np.allclose(t[3],[0,0,0,1]):
        raise ValueError('This version requires the calibrated near-vertical topdown camera and flat z=0 map')
    if not np.isclose(k[0, 0], k[1, 1], rtol=1e-5):
        raise ValueError('Square pixels are required for metric stroke measurements')
    return float(t[2, 3] / k[0, 0])

def xyworld(uv, meta):
    ray = np.c_[np.asarray(uv, float), np.ones(len(uv))] @ np.linalg.inv(np.asarray(meta['intrinsic'])).T
    t = np.asarray(meta['optical_to_world_carla']); ray = ray @ t[:3, :3].T
    if np.any(np.abs(ray[:, 2]) < 1e-9):
        raise ValueError('Camera ray parallel to ground')
    return t[:3, 3] + ray * (-t[2, 3] / ray[:, 2:3])

def project(xyz, meta):
    p = transform(xyz, np.linalg.inv(np.asarray(meta['optical_to_world_carla'])))
    uv = p @ np.asarray(meta['intrinsic']).T
    return uv[:, :2] / uv[:, 2:3]

def uid(points, prefix='observed'):
    p = np.round(np.asarray(points), 4).tolist()
    a, b = json.dumps(p, separators=(',', ':')), json.dumps(p[::-1], separators=(',', ':'))
    return prefix + ':' + hashlib.sha256(min(a, b).encode()).hexdigest()[:20]

def parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'LineString':
        return [geometry]
    return [p for item in getattr(geometry, 'geoms', []) for p in parts(item)]

def sample(line, step=.05):
    ss = np.linspace(0, line.length, max(2, int(np.ceil(line.length / step)) + 1))
    return ss, np.asarray([line.interpolate(s).coords[0] for s in ss])[:, :2]

def tangent(line, s, window=.4):
    a = np.asarray(line.interpolate(max(0, s-window)).coords[0])[:2]
    b = np.asarray(line.interpolate(min(line.length, s+window)).coords[0])[:2]
    v = b-a
    return v / max(np.linalg.norm(v), 1e-12)

def endpoint(points, start=False):
    p = np.asarray(points)[:, :2]
    p = p[::-1] if start else p
    line = LineString(p); ss = np.linspace(max(0, line.length-1.), line.length, 12)
    xy = np.asarray([line.interpolate(s).coords[0] for s in ss]); q = ss-ss[-1]
    if len(np.unique(xy, axis=0)) < 3:
        v = p[-1]-p[0]
    else:
        linear = np.polyfit(q, xy, 1); quadratic = np.polyfit(q, xy, 2)
        e1 = np.mean((np.polyval(linear, q[:, None])-xy)**2)
        e2 = np.mean((np.polyval(quadratic, q[:, None])-xy)**2)
        v = quadratic[-2] if e2 < e1*.0625 else linear[0]
    v = v/max(np.linalg.norm(v), 1e-12)
    return -v if start else v

def bridge(pa, pb, step=.04):
    pa, pb = np.asarray(pa)[:, :2], np.asarray(pb)[:, :2]
    gap = float(np.linalg.norm(pb[0]-pa[-1]))
    ta, tb = endpoint(pa), endpoint(pb, True)
    curve = CubicHermiteSpline([0, gap], np.stack([pa[-1], pb[0]]), np.stack([ta, tb]))
    return curve(np.linspace(0, gap, max(8, int(np.ceil(gap/step))+1))), ta, tb

def trace(mask):
    """Trace the observed skeleton, splitting only at graph junctions/endpoints."""
    ys, xs = np.where(skeletonize(mask)); pixels = set(zip(xs.tolist(), ys.tolist())); adj = {}
    for x, y in pixels:
        neighbors = []
        for dx, dy in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
            if (x+dx,y+dy) in pixels and not (dx and dy and ((x+dx,y) in pixels or (x,y+dy) in pixels)):
                neighbors.append((x+dx,y+dy))
        adj[(x,y)] = sorted(neighbors)
    visited, paths = set(), []
    for start in sorted(pixels, key=lambda p: (len(adj[p]) == 2, p)):
        for nxt in adj[start]:
            edge = tuple(sorted((start,nxt)))
            if edge in visited:
                continue
            path = [start,nxt]; visited.add(edge); previous,current = start,nxt
            while len(adj[current]) == 2 and current != start:
                nxt = next(q for q in adj[current] if q != previous); edge = tuple(sorted((current,nxt)))
                if edge in visited:
                    break
                visited.add(edge); path.append(nxt); previous,current = current,nxt
            if len(path) > 1:
                paths.append(np.asarray(path, float))
    branches = np.zeros(mask.shape, np.uint8)
    for (x,y), neighbors in adj.items():
        if len(neighbors) > 2:
            branches[y,x] = 1
    return paths, branches

def local_bend(line, interval=.5):
    ss = np.linspace(0,line.length,max(2,int(line.length/.1)+1))
    vectors = np.asarray([tangent(line,float(s),.2) for s in ss])
    k = min(len(ss)-1,max(1,int(round(interval/max(ss[1]-ss[0],1e-9)))))
    return float(np.degrees(np.arccos(np.clip((vectors[k:]*vectors[:-k]).sum(axis=1),-1,1))).max())
