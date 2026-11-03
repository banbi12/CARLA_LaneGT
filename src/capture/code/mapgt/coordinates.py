import numpy as np
from .common import require

S = np.diag([1., -1., 1., 1.])
NATIVE_FROM_MAP = np.array([[0., 1., 0., 0.], [-1., 0., 0., 0.],
                            [0., 0., 1., 0.], [0., 0., 0., 1.]])
MAP_FROM_NATIVE = NATIVE_FROM_MAP.T
OPTICAL_TO_CARLA = np.array([[0.,0.,1.,0.],[1.,0.,0.,0.],
                              [0.,-1.,0.,0.],[0.,0.,0.,1.]])
ACTOR_FROM_NATIVE_FLU = np.eye(4)
ACTOR_FROM_NATIVE_FLU[0, 3] = -1.317


def rigid(value, name):
    t = np.asarray(value, dtype=np.float64)
    require(t.shape == (4,4) and np.isfinite(t).all(), name+': INVALID_MATRIX')
    require(np.allclose(t[3], [0,0,0,1], atol=1e-8, rtol=0), name+': HOMOGENEOUS_ROW')
    r = t[:3,:3]
    require(np.allclose(r.T@r, np.eye(3), atol=2e-5, rtol=0) and
            abs(np.linalg.det(r)-1) < 2e-5, name+': NOT_RIGID')
    return t


def transform(t, points):
    p = np.asarray(points, dtype=np.float64)
    require(p.ndim == 2 and p.shape[1] in (3,4) and np.isfinite(p).all(), 'INVALID_XYZ')
    if p.shape[1] == 3:
        p = np.column_stack((p, np.ones(len(p))))
    return (p @ np.asarray(t).T)[:, :3]


def map_from_world(frame):
    return MAP_FROM_NATIVE @ np.linalg.inv(np.asarray(frame['native_to_world_flu'])) @ S


def optical_from_world(camera):
    return np.linalg.inv(np.asarray(camera['sensor_to_world_carla']) @ OPTICAL_TO_CARLA)


def pixels(k, optical_xyz):
    p = np.asarray(optical_xyz)
    good = p[:,2] > .5
    q = p[good] @ np.asarray(k).T
    return q[:,:2]/q[:,2:3], good
