"""Model-neutral frame metadata and CARLA-to-optical coordinate conversions.

Matrices use column vectors and map coordinates from the frame named on the
right of ``to`` into the frame named on the left. CARLA/Unreal uses forward,
right, up; the canonical ego/world frame uses forward, left, up.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


CAMERAS = (
    "CAM_FRONT_LEFT", "CAM_FRONT", "CAM_FRONT_RIGHT",
    "CAM_BACK_LEFT", "CAM_BACK", "CAM_BACK_RIGHT",
)

CARLA_TO_FLU = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, -1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
# Standard optical coordinates: x right, y down, z forward. This maps an
# optical vector into a CARLA camera-local vector (x forward, y right, z up).
OPTICAL_TO_CARLA_SENSOR = (
    (0.0, 0.0, 1.0, 0.0),
    (1.0, 0.0, 0.0, 0.0),
    (0.0, -1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(len(b)))
                       for j in range(len(b[0]))) for i in range(len(a)))


def transform(matrix, xyz):
    p = tuple(xyz) + (1.0,)
    out = tuple(sum(matrix[i][j] * p[j] for j in range(4)) for i in range(4))
    if not math.isclose(out[3], 1.0, abs_tol=1e-8):
        raise ValueError("Expected a rigid homogeneous transform")
    return out[:3]


def inverse_rigid(matrix):
    validate_rigid(matrix)
    # CARLA publishes transforms with float32 rotation entries. Their columns
    # are nearly orthogonal but not exact, so transposing can add micrometre
    # round-trip error at typical LiDAR ranges. Invert the measured 3x3 block.
    a, b, c = matrix[0][:3]
    d, e, f = matrix[1][:3]
    g, h, i = matrix[2][:3]
    cofactor = ((e * i - f * h, c * h - b * i, b * f - c * e),
                (f * g - d * i, a * i - c * g, c * d - a * f),
                (d * h - e * g, b * g - a * h, a * e - b * d))
    determinant = a * cofactor[0][0] + b * cofactor[1][0] + c * cofactor[2][0]
    result = [[0.0] * 4 for _ in range(4)]
    for i in range(3):
        for j in range(3):
            result[i][j] = cofactor[i][j] / determinant
        result[i][3] = -sum(result[i][j] * matrix[j][3] for j in range(3))
    result[3][3] = 1.0
    return tuple(tuple(row) for row in result)


def validate_rigid(matrix, *, handedness=None):
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValueError("Expected a 4x4 matrix")
    if any(not math.isfinite(v) for row in matrix for v in row):
        raise ValueError("Matrix has a non-finite value")
    if any(abs(matrix[3][j] - (1.0 if j == 3 else 0.0)) > 1e-6
           for j in range(4)):
        raise ValueError("Invalid homogeneous last row")
    for i in range(3):
        for j in range(3):
            dot = sum(matrix[k][i] * matrix[k][j] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > 1e-5:
                raise ValueError("Rotation axes are not orthonormal")
    r = matrix
    det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
    if abs(abs(det) - 1.0) > 1e-5 or (handedness is not None and det * handedness < 0.99999):
        raise ValueError("Unexpected rotation handedness")


def carla_ego_to_flu_world(carla_ego_to_world):
    """Convert a CARLA actor matrix to a right-handed FLU-to-FLU matrix."""
    validate_rigid(carla_ego_to_world, handedness=1)
    return matmul(matmul(CARLA_TO_FLU, carla_ego_to_world), CARLA_TO_FLU)


def optical_to_flu_ego(carla_sensor_to_ego):
    """Convert a CARLA sensor matrix to optical-camera-to-FLU-ego."""
    validate_rigid(carla_sensor_to_ego, handedness=1)
    result = matmul(matmul(CARLA_TO_FLU, carla_sensor_to_ego),
                    OPTICAL_TO_CARLA_SENSOR)
    validate_rigid(result, handedness=1)
    return result


def project_ego_point(point_ego, optical_to_ego, intrinsic):
    x, y, z = transform(inverse_rigid(optical_to_ego), point_ego)
    if z <= 0:
        raise ValueError("Point is behind the camera")
    u = (intrinsic[0][0] * x + intrinsic[0][1] * y + intrinsic[0][2] * z) / z
    v = (intrinsic[1][0] * x + intrinsic[1][1] * y + intrinsic[1][2] * z) / z
    return u, v, z


def unproject_to_ego(u, v, depth, optical_to_ego, intrinsic):
    if depth <= 0:
        raise ValueError("Depth must be positive")
    fx, fy = intrinsic[0][0], intrinsic[1][1]
    if fx <= 0 or fy <= 0:
        raise ValueError("Focal lengths must be positive")
    y = (v - intrinsic[1][2]) * depth / fy
    x = ((u - intrinsic[0][2]) * depth - intrinsic[0][1] * y) / fx
    return transform(optical_to_ego, (x, y, depth))


def png_dimensions(path):
    content = Path(path).read_bytes()
    if content[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Invalid PNG header: {path}")
    offset = 8
    dimensions = None
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(content):
            break
        kind = content[offset + 4:offset + 8]
        payload = content[offset + 8:offset + 8 + length]
        checksum = struct.unpack(">I", content[offset + 8 + length:end])[0]
        if zlib.crc32(kind + payload) != checksum:
            raise ValueError(f"PNG checksum error: {path}")
        if kind == b"IHDR":
            dimensions = struct.unpack(">II", payload[:8])
        if kind == b"IEND":
            if end != len(content) or dimensions is None:
                break
            return dimensions
        offset = end
    raise ValueError(f"Incomplete PNG: {path}")


@dataclass(frozen=True)
class FrameBundle:
    scene_id: str
    frame_id: int
    sim_time_s: float
    ego_to_world_carla: tuple
    cameras: dict
    scene: dict

    @classmethod
    def from_json(cls, path, expected_cameras=None):
        path = Path(path)
        data = json.loads(path.read_text())
        cameras = data["cameras"]
        expected = tuple(CAMERAS if expected_cameras is None else expected_cameras)
        if set(cameras) != set(expected):
            raise ValueError(f"Expected named cameras: {expected}")
        if data["frame_id"] < 0 or not math.isfinite(data["sim_time_s"]):
            raise ValueError("Invalid frame or simulation time")
        validate_rigid(data["ego_to_world_carla"], handedness=1)
        for name in expected:
            camera = cameras[name]
            if camera["frame_id"] != data["frame_id"]:
                raise ValueError(f"Stale camera frame: {name}")
            if abs(camera["sim_time_s"] - data["sim_time_s"]) > 0.001:
                raise ValueError(f"Camera timestamp mismatch: {name}")
            image = (path.parent / camera["image"]).resolve()
            if not image.is_file() or png_dimensions(image) != (camera["width"], camera["height"]):
                raise ValueError(f"Missing or wrong-size PNG: {name}")
            validate_rigid(camera["sensor_to_ego_carla"], handedness=1)
            k = camera["intrinsic"]
            if len(k) != 3 or any(len(row) != 3 for row in k) or k[0][0] <= 0 or k[1][1] <= 0:
                raise ValueError(f"Invalid intrinsic: {name}")
        scene = data["scene"]
        if not isinstance(scene, dict) or not scene.get("map"):
            raise ValueError("Scene metadata must include map")
        return cls(data["scene_id"], data["frame_id"], data["sim_time_s"],
                   tuple(tuple(row) for row in data["ego_to_world_carla"]),
                   cameras, scene)

    def ego_to_world(self):
        return carla_ego_to_flu_world(self.ego_to_world_carla)

    def optical_to_ego(self, camera):
        return optical_to_flu_ego(self.cameras[camera]["sensor_to_ego_carla"])
