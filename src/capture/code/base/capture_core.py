"""CARLA-independent scheduling, synchronization and atomic frame writing."""

import json
import math
import queue
import shutil
import time
from pathlib import Path

from frame_bundle import CAMERAS, FrameBundle


def rate_settings(sim_hz, trajectory_hz, camera_hz):
    if sim_hz <= 0 or trajectory_hz <= 0 or camera_hz <= 0:
        raise ValueError("Frequencies must be positive")
    if not math.isclose(sim_hz / trajectory_hz, round(sim_hz / trajectory_hz)):
        raise ValueError("Trajectory frequency must divide simulation frequency")
    if not math.isclose(sim_hz / camera_hz, round(sim_hz / camera_hz)):
        raise ValueError("Camera frequency must divide simulation frequency")
    return int(round(sim_hz / trajectory_hz)), int(round(sim_hz / camera_hz))


def collect_group(inboxes, target_frame, target_time, timeout_s, camera_names=CAMERAS):
    """Consume exactly one same-frame camera group, discarding older callbacks."""
    deadline = time.monotonic() + timeout_s
    images = {}
    for name in camera_names:
        inbox = inboxes[name]
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Missing {name} at frame {target_frame}")
            try:
                image = inbox.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f"Missing {name} at frame {target_frame}") from None
            if image.frame < target_frame:
                continue
            if image.frame != target_frame or abs(image.timestamp - target_time) > 0.001:
                raise ValueError(f"Frame/time mismatch for {name}: {image.frame} at {image.timestamp}")
            images[name] = image
            break
    return images


def write_frame(scene_dir, metadata, images, camera_names=CAMERAS):
    frame_id = metadata["frame_id"]
    frames_dir = Path(scene_dir) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    final = frames_dir / str(frame_id)
    partial = frames_dir / f".{frame_id}.partial"
    if final.exists() or partial.exists():
        raise FileExistsError(f"Frame already exists: {frame_id}")
    partial.mkdir()
    try:
        for name in camera_names:
            images[name].save_to_disk(str(partial / f"{name}.png"))
        (partial / "frame.json").write_text(json.dumps(metadata, indent=2) + "\n")
        FrameBundle.from_json(partial / "frame.json", expected_cameras=camera_names)
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial)
        raise
    return final / "frame.json"
