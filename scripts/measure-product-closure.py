#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Iterable


def _load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text())
    package = data.get("package", {})
    name = package.get("name")
    if not name or not isinstance(data.get("blobs"), list):
        raise ValueError(f"invalid package manifest: {path}")
    blobs: dict[str, int] = {}
    meta_merkle = None
    for blob in data["blobs"]:
        merkle = blob["merkle"]
        size = int(blob["size"])
        if merkle in blobs and blobs[merkle] != size:
            raise ValueError(f"inconsistent blob size in {path}: {merkle}")
        blobs[merkle] = size
        if blob.get("path") == "meta/":
            meta_merkle = merkle
    return {
        "path": str(path),
        "name": name,
        "version": str(package.get("version", "0")),
        "identity": f"{name}@{package.get('version', '0')}:{meta_merkle or 'no-meta'}",
        "blobs": blobs,
    }


def _merge_blob_sizes(packages: Iterable[dict]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for package in packages:
        for merkle, size in package["blobs"].items():
            if merkle in merged and merged[merkle] != size:
                raise ValueError(f"inconsistent size for blob {merkle}: {merged[merkle]} vs {size}")
            merged[merkle] = size
    return merged


def _delivery_size(delivery_dir: Path | None, merkle: str) -> int | None:
    if delivery_dir is None:
        return None
    path = delivery_dir / merkle
    return path.stat().st_size if path.is_file() else None


def _summary(packages: list[dict], delivery_dir: Path | None) -> dict:
    blobs = _merge_blob_sizes(packages)
    delivery = {m: _delivery_size(delivery_dir, m) for m in blobs}
    missing = sorted(m for m, size in delivery.items() if size is None)
    return {
        "packages": len({p["identity"] for p in packages}),
        "unique_blobs": len(blobs),
        "uncompressed_bytes": sum(blobs.values()),
        "delivery_bytes": sum(size for size in delivery.values() if size is not None),
        "missing_delivery_blobs": missing,
    }


def measure(
    *,
    tiers: dict[str, list[Path]],
    app_manifests: dict[str, list[Path]],
    delivery_dir: Path | None,
) -> dict:
    manifest_cache: dict[Path, dict] = {}

    def package(path: Path) -> dict:
        resolved = path.resolve()
        if resolved not in manifest_cache:
            manifest_cache[resolved] = _load_manifest(resolved)
        return manifest_cache[resolved]

    tier_packages = {name: [package(path) for path in paths] for name, paths in tiers.items()}
    all_refs = [p for packages in tier_packages.values() for p in packages]
    image = _summary(all_refs, delivery_dir)
    image["package_references"] = len(all_refs)
    image["unique_packages"] = image.pop("packages")
    repository_refs = [
        package
        for tier_name in ("system", "base", "cache", "anchored_automatic")
        for package in tier_packages.get(tier_name, [])
    ]
    repository = _summary(repository_refs, delivery_dir)
    repository["package_references"] = len(repository_refs)
    repository["unique_packages"] = repository.pop("packages")

    app_packages = {name: [package(path) for path in paths] for name, paths in app_manifests.items()}
    app_blob_sets = {
        name: set(_merge_blob_sizes(packages)) for name, packages in app_packages.items()
    }
    owners: dict[str, set[str]] = defaultdict(set)
    for name, merkles in app_blob_sets.items():
        for merkle in merkles:
            owners[merkle].add(name)
    all_app_packages = [p for packages in app_packages.values() for p in packages]
    app_blob_sizes = _merge_blob_sizes(all_app_packages)

    apps = {}
    for name, packages in sorted(app_packages.items()):
        summary = _summary(packages, delivery_dir)
        exclusive = [m for m in app_blob_sets[name] if len(owners[m]) == 1]
        summary["exclusive_blobs"] = len(exclusive)
        summary["exclusive_uncompressed_bytes"] = sum(app_blob_sizes[m] for m in exclusive)
        summary["exclusive_delivery_bytes"] = sum(
            size for m in exclusive if (size := _delivery_size(delivery_dir, m)) is not None
        )
        apps[name] = summary

    shared = [m for m, names in owners.items() if len(names) > 1]
    package_rows = []
    for p in {x["identity"]: x for x in all_refs}.values():
        package_rows.append({
            "name": p["name"],
            "identity": p["identity"],
            "blobs": len(p["blobs"]),
            "logical_uncompressed_bytes": sum(p["blobs"].values()),
        })
    package_rows.sort(key=lambda row: (-row["logical_uncompressed_bytes"], row["name"]))
    blob_rows = [
        {
            "merkle": merkle,
            "uncompressed_bytes": size,
            "delivery_bytes": _delivery_size(delivery_dir, merkle),
        }
        for merkle, size in _merge_blob_sizes(all_refs).items()
    ]
    blob_rows.sort(key=lambda row: (-row["uncompressed_bytes"], row["merkle"]))

    return {
        "image": image,
        "assembly": image,
        "repository": repository,
        "tiers": {
            name: _summary(packages, delivery_dir)
            for name, packages in sorted(tier_packages.items())
        },
        "apps": apps,
        "app_shared": {
            "blobs": len(shared),
            "uncompressed_bytes": sum(app_blob_sizes[m] for m in shared),
            "delivery_bytes": sum(
                size for m in shared if (size := _delivery_size(delivery_dir, m)) is not None
            ),
        },
        "top_packages": package_rows[:20],
        "top_blobs": blob_rows[:20],
    }


def _markdown(report: dict) -> str:
    image = report["assembly"]
    repository = report["repository"]
    lines = [
        "# Fuchsia product closure measurement",
        "",
        f"- Assembly package references: {image['package_references']:,}",
        f"- Assembly unique packages: {image['unique_packages']:,}",
        f"- Assembly unique blobs: {image['unique_blobs']:,}",
        f"- Assembly uncompressed blob bytes: {image['uncompressed_bytes']:,}",
        f"- Embedded repository package references: {repository['package_references']:,}",
        f"- Embedded repository unique packages: {repository['unique_packages']:,}",
        f"- Embedded repository unique blobs: {repository['unique_blobs']:,}",
        f"- Embedded repository uncompressed bytes: {repository['uncompressed_bytes']:,}",
        f"- Embedded repository delivery bytes: {repository['delivery_bytes']:,}",
        f"- Embedded repository missing delivery blobs: {len(repository['missing_delivery_blobs']):,}",
        "",
        "## Tiers",
        "",
        "| Tier | Packages | Blobs | Uncompressed | Delivery | Missing |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in report["tiers"].items():
        lines.append(
            f"| {name} | {row['packages']:,} | {row['unique_blobs']:,} | "
            f"{row['uncompressed_bytes']:,} | {row['delivery_bytes']:,} | "
            f"{len(row['missing_delivery_blobs']):,} |"
        )
    lines += ["", "## App package groups", "", "| App | Packages | Blobs | Uncompressed | Exclusive | Delivery |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in report["apps"].items():
        lines.append(
            f"| {name} | {row['packages']:,} | {row['unique_blobs']:,} | "
            f"{row['uncompressed_bytes']:,} | {row['exclusive_uncompressed_bytes']:,} | "
            f"{row['delivery_bytes']:,} |"
        )
    lines += ["", "## Largest logical packages", ""]
    for row in report["top_packages"]:
        lines.append(f"- {row['name']}: {row['logical_uncompressed_bytes']:,} bytes, {row['blobs']} blobs")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-assembly", type=Path, required=True)
    parser.add_argument("--execroot", type=Path, required=True)
    parser.add_argument("--delivery-dir", type=Path)
    parser.add_argument("--app", action="append", default=[], metavar="NAME=MANIFEST[,MANIFEST]")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    image = json.loads(args.image_assembly.read_text())
    tier_names = ("system", "base", "cache", "anchored_automatic", "anchored_on_demand", "on_demand", "bootfs_packages")
    tiers = {
        name: [args.execroot / rel for rel in image.get(name, [])]
        for name in tier_names
        if image.get(name)
    }
    apps: dict[str, list[Path]] = {}
    for value in args.app:
        name, sep, raw_paths = value.partition("=")
        if not sep or not name or not raw_paths:
            raise SystemExit(f"invalid --app value: {value}")
        apps[name] = [Path(raw) for raw in raw_paths.split(",")]

    report = measure(tiers=tiers, app_manifests=apps, delivery_dir=args.delivery_dir)
    report["bootfs_files"] = {
        "files": len(image.get("bootfs_files", [])),
        "source_bytes": sum(
            (args.execroot / entry["source"]).stat().st_size
            for entry in image.get("bootfs_files", [])
        ),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.output_md.write_text(_markdown(report))
    print(json.dumps({
        "assembly_package_references": report["assembly"]["package_references"],
        "assembly_unique_packages": report["assembly"]["unique_packages"],
        "assembly_unique_blobs": report["assembly"]["unique_blobs"],
        "repository_unique_packages": report["repository"]["unique_packages"],
        "repository_unique_blobs": report["repository"]["unique_blobs"],
        "repository_uncompressed_bytes": report["repository"]["uncompressed_bytes"],
        "repository_delivery_bytes": report["repository"]["delivery_bytes"],
        "repository_missing_delivery_blobs": len(report["repository"]["missing_delivery_blobs"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
