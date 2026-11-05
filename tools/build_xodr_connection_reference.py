#!/usr/bin/env python3
"""Build a pinned XODR-only V4.1 divider connection reference.

The reference contains the stitched V4.1 divider chains, not the raw roadMark
fragments used by the legacy V4.2 connection prior. It is consumed by the
semantic connection guard as a map path/route authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_id(points: list[list[float]]) -> str:
    rounded = [[round(float(v), 4) for v in p] for p in points]
    forward = json.dumps(rounded, separators=(",", ":"))
    reverse = json.dumps(rounded[::-1], separators=(",", ":"))
    payload = min(forward, reverse)
    return "xodr_v41:" + hashlib.sha256(payload.encode()).hexdigest()[:20]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--xodr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pin", type=Path, required=True)
    args = parser.parse_args()

    world = json.loads(args.world.read_text())
    xodr_sha = sha256(args.xodr)
    if world.get("generator") != "xodr_only_legacy_v41_topology_local_stitched":
        raise SystemExit("Expected the XODR-only V4.1 world generator")
    if world.get("xodr_sha256") != xodr_sha:
        raise SystemExit("World/XODR fingerprint mismatch")
    dividers = world["legacy_world"]["dividers"]
    if not dividers:
        raise SystemExit("No stitched dividers in world")

    features = {}
    for item in dividers:
        points = [[float(x), float(y), 0.0] for x, y in item["points"]]
        identifier = stable_id(points)
        if identifier in features:
            raise SystemExit("Duplicate divider id: " + identifier)
        features[identifier] = {
            "id": identifier,
            "class": "divider",
            "source": item.get("source", {}),
            "points_xyz": points,
        }

    reference = {
        "schema": "xodr_connection_reference_v1",
        "map_identity": "Town10HD@" + xodr_sha,
        "xodr_sha256": xodr_sha,
        "source_world_file_sha256": sha256(args.world),
        "source_world_generator": world["generator"],
        "scope": "generated-divider-bridges-only; observations never removed by missing map support",
        "features": features,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reference, ensure_ascii=False, indent=1) + "\n")
    pin = {
        "schema": "pinned_xodr_connection_reference_v1",
        "asset": args.output.name,
        "sha256": sha256(args.output),
        "xodr_sha256": xodr_sha,
        "source_world_file_sha256": sha256(args.world),
        "features": len(features),
        "source": "xodr_only_legacy_v41_topology_local_stitched.legacy_world.dividers",
        "approved_for_training": False,
    }
    args.pin.parent.mkdir(parents=True, exist_ok=True)
    args.pin.write_text(json.dumps(pin, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"passed": True, "features": len(features), "asset": str(args.output), "pin": str(args.pin)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
