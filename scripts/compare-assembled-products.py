#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

APPS = ("fuchsia_browser", "fuchsia_terminal", "fuchsia_files", "fuchsia_settings", "workbench_session")

def summarize_assembled(path: Path) -> dict:
    data = json.loads(path.read_text())
    sets: dict[str, list[dict]] = {}
    blob_sizes: dict[str, int] = {}
    for image in data["images"]:
        for set_name, packages in image.get("contents", {}).get("packages", {}).items():
            sets.setdefault(set_name, []).extend(packages)
            for package in packages:
                for blob in package.get("blobs", []):
                    merkle = blob["merkle"]
                    size = int(blob["used_space_in_blobfs"])
                    if merkle in blob_sizes and blob_sizes[merkle] != size:
                        raise ValueError(f"inconsistent used-space for {merkle}")
                    blob_sizes[merkle] = size
    package_names = {name for packages in sets.values() for name in (p["name"] for p in packages)}
    app_bytes = {}
    for app in APPS:
        merkles = {}
        for packages in sets.values():
            for package in packages:
                if package["name"] == app:
                    for blob in package.get("blobs", []):
                        merkles[blob["merkle"]] = int(blob["used_space_in_blobfs"])
        app_bytes[app] = sum(merkles.values()) if merkles else None
    return {
        "package_sets": {name: len(packages) for name, packages in sorted(sets.items())},
        "unique_packages": len(package_names),
        "package_names": sorted(package_names),
        "unique_blobs": len(blob_sizes),
        "used_space_in_blobfs": sum(blob_sizes.values()),
        "app_used_space_in_blobfs": app_bytes,
    }

def tuf_targets(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return sorted(data["signed"]["targets"])

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-system", type=Path, required=True)
    parser.add_argument("--slim-system", type=Path, required=True)
    parser.add_argument("--baseline-targets", type=Path, required=True)
    parser.add_argument("--slim-targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = summarize_assembled(args.baseline_system)
    slim = summarize_assembled(args.slim_system)
    baseline_targets = tuf_targets(args.baseline_targets)
    slim_targets = tuf_targets(args.slim_targets)
    app_targets = {
        app: {
            "baseline": [name for name in baseline_targets if name.startswith(app + "/")],
            "slim": [name for name in slim_targets if name.startswith(app + "/")],
        }
        for app in APPS
    }
    report = {
        "baseline": {k: v for k, v in baseline.items() if k != "package_names"} | {"tuf_targets": len(baseline_targets)},
        "slim": {k: v for k, v in slim.items() if k != "package_names"} | {"tuf_targets": len(slim_targets)},
        "delta": {
            "unique_packages": slim["unique_packages"] - baseline["unique_packages"],
            "unique_blobs": slim["unique_blobs"] - baseline["unique_blobs"],
            "used_space_in_blobfs": slim["used_space_in_blobfs"] - baseline["used_space_in_blobfs"],
            "tuf_targets": len(slim_targets) - len(baseline_targets),
        },
        "removed_packages": sorted(set(baseline["package_names"]) - set(slim["package_names"])),
        "added_packages": sorted(set(slim["package_names"]) - set(baseline["package_names"])),
        "app_targets": app_targets,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
