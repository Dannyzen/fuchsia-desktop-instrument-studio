#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("measure-product-closure.py")
spec = importlib.util.spec_from_file_location("measure_product_closure", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_manifest(path: Path, name: str, blobs: list[tuple[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "package": {"name": name, "version": "0"},
        "blobs": [
            {"path": f"data/{i}", "merkle": merkle, "size": size, "source_path": f"../blobs/{merkle}"}
            for i, (merkle, size) in enumerate(blobs)
        ],
    }))


class ClosureMeasurementTest(unittest.TestCase):
    def test_deduplicates_image_tiers_and_real_delivery_sizes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.json"
            b = root / "b.json"
            write_manifest(a, "app-a", [("shared", 100), ("only-a", 50)])
            write_manifest(b, "app-b", [("shared", 100), ("only-b", 70)])
            delivery = root / "delivery"
            delivery.mkdir()
            for merkle, size in [("shared", 60), ("only-a", 25), ("only-b", 35)]:
                (delivery / merkle).write_bytes(b"x" * size)

            report = module.measure(
                tiers={"base": [a], "cache": [b], "on_demand": [a]},
                app_manifests={"a": [a], "b": [b]},
                delivery_dir=delivery,
            )

            self.assertEqual(report["image"]["package_references"], 3)
            self.assertEqual(report["image"]["unique_packages"], 2)
            self.assertEqual(report["image"]["unique_blobs"], 3)
            self.assertEqual(report["image"]["uncompressed_bytes"], 220)
            self.assertEqual(report["image"]["delivery_bytes"], 120)
            self.assertEqual(report["tiers"]["base"]["packages"], 1)
            self.assertEqual(report["tiers"]["on_demand"]["packages"], 1)
            self.assertEqual(report["repository"]["unique_packages"], 2)
            self.assertEqual(report["repository"]["unique_blobs"], 3)
            self.assertEqual(report["repository"]["delivery_bytes"], 120)

    def test_attributes_shared_and_exclusive_app_blobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.json"
            b = root / "b.json"
            write_manifest(a, "app-a", [("shared", 100), ("only-a", 50)])
            write_manifest(b, "app-b", [("shared", 100), ("only-b", 70)])
            delivery = root / "delivery"
            delivery.mkdir()
            for merkle, size in [("shared", 60), ("only-a", 25), ("only-b", 35)]:
                (delivery / merkle).write_bytes(b"x" * size)

            report = module.measure(
                tiers={"cache": [a, b]},
                app_manifests={"a": [a], "b": [b]},
                delivery_dir=delivery,
            )

            self.assertEqual(report["apps"]["a"]["uncompressed_bytes"], 150)
            self.assertEqual(report["apps"]["a"]["exclusive_uncompressed_bytes"], 50)
            self.assertEqual(report["apps"]["b"]["exclusive_uncompressed_bytes"], 70)
            self.assertEqual(report["app_shared"]["blobs"], 1)
            self.assertEqual(report["app_shared"]["uncompressed_bytes"], 100)
            self.assertEqual(report["app_shared"]["delivery_bytes"], 60)


if __name__ == "__main__":
    unittest.main()
