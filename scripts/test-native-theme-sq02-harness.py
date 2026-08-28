#!/usr/bin/env python3
"""Focused negative and determinism tests for the SQ-02 delivery harness."""

from __future__ import annotations

from collections import Counter
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import tarfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))
import sq02_harness as h  # noqa: E402


def launcher_module():
    path = ROOT / "scripts/run-native-theme-sq02.py"
    spec = importlib.util.spec_from_file_location("sq02_launcher", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_static_root(destination: Path) -> None:
    for relative in (
        "scripts/run-native-theme-sq02.py", "scripts/test-native-theme-sq02.py",
        "tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py",
        "tools/native_theme/sq02-rust-qualifier/Cargo.toml", "tools/native_theme/sq02-rust-qualifier/Cargo.lock",
        "tools/native_theme/sq02-rust-qualifier/rust-toolchain.toml", "tools/native_theme/sq02-rust-qualifier/src/main.rs",
    ):
        target = destination / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def payload_fixture():
    packages = [{"bytes": 1, "file": f"p-{i}.json", "id": f"p-{i}", "semantic_sha256": f"{i+1:064x}",
                 "sha256": f"{i+10:064x}"} for i in range(5)]
    accepted = {"accepted": True, "code": None, "layer": "accepted", "package_sha256": "1" * 64,
                "semantic_sha256": "2" * 64}
    boundaries = [{"bytes": 262143, "compiler": accepted, "contract": accepted},
                  {"bytes": 262144, "compiler": accepted, "contract": accepted},
                  {"bytes": 262145, "compiler": {"accepted": False, "code": "E_CANONICAL_SIZE", "layer": "compiler"},
                   "contract": {"accepted": False, "code": "E_LIMIT_PACK", "layer": "bounds"}}]
    rust_boundaries = [{"accepted": True, "bytes": 262143, "code": None},
                       {"accepted": True, "bytes": 262144, "code": None},
                       {"accepted": False, "bytes": 262145, "code": "E_LIMIT_PACK"}]
    return {"catalog": {"index.json": {"bytes": 1, "sha256": "3" * 64}}, "corpus_bytes_sha256": "4" * 64,
            "corpus_manifest_sha256": "5" * 64, "diagnostic_mapping": [], "packages": packages,
            "python_boundaries": boundaries, "rust": {"boundaries": rust_boundaries,
            "corpus": {"accepted": 32, "executed": 256, "rejected": 224}, "requirement_ids": list(h.REQUIREMENT_IDS)},
            "rust_raw_sha256": "6" * 64, "size_observations": {"catalog_bytes": 1,
            "largest_catalog_receipt_bytes": 1, "largest_package_bytes": 1, "largest_source_bytes": 1}}


class CoreTests(unittest.TestCase):
    def test_canonical_and_strict_json(self):
        self.assertEqual(h.canonical_json_bytes({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')
        self.assertEqual(h.strict_json(b'{"a":1}\n'), {"a": 1})
        for raw in (b'{"a":1}', b'{"a":1}\n\n', b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b'\xff\n'):
            with self.subTest(raw=raw), self.assertRaises(h.QualificationError):
                h.strict_json(raw)
        with self.assertRaises(h.QualificationError):
            h.canonical_json_bytes({"x": float("nan")})
        with self.assertRaises(h.QualificationError):
            h.strict_json(b'{"a": 1}\n')

    def test_network_monkeypatch_is_reversible_defense_only(self):
        original = socket.socket.connect
        undo = h.install_python_network_denial()
        try:
            with self.assertRaises(PermissionError):
                socket.create_connection(("127.0.0.1", 9))
        finally:
            undo()
        self.assertIs(socket.socket.connect, original)

    def test_subprocess_allowlist_rejects_unknown_shell_and_malformed(self):
        git_ok = ["git", "rev-parse", "HEAD"]
        self.assertTrue(h.allowed_subprocess(git_ok, ROOT))
        self.assertTrue(h.allowed_subprocess(["git", "archive", "--format=tar", "0" * 40], ROOT))
        for command in ("git status", [], ["sh", "-c", "true"], ["git", "push"], [1]):
            self.assertFalse(h.allowed_subprocess(command, ROOT))
        with self.assertRaises(h.QualificationError):
            h.run_allowed(["sh", "-c", "true"], ROOT)
        with self.assertRaises(h.QualificationError):
            h.run_allowed(git_ok, ROOT, shell=True)
        cargo = Path("/bin/cargo")
        valid = [str(cargo), "run", "--locked", "--offline", "--manifest-path", "m",
                 "--target-dir", "t", "--", "--packages", "p", "--corpus", "c"]
        self.assertTrue(h.allowed_subprocess(valid, ROOT, cargo=cargo))
        malformed = [str(cargo), "run", "--offline", "--locked", "--manifest-path", "m",
                     "--target-dir", "t", "--", "--packages", "p", "--corpus", "c"]
        self.assertFalse(h.allowed_subprocess(malformed, ROOT, cargo=cargo))
        self.assertTrue(h.allowed_subprocess([str(cargo), "--version", "--verbose"], ROOT, cargo=cargo))
        self.assertTrue(h.allowed_subprocess(["/bin/rustc", "--version", "--verbose"], ROOT, rustc=Path("/bin/rustc")))
        coverage_run = [sys.executable, "-m", "coverage", "run", "--branch", "scripts/test-native-theme-sq02-harness.py"]
        coverage_json = [sys.executable, "-m", "coverage", "json", "-o", "report.json"]
        self.assertTrue(h.allowed_subprocess(coverage_run, ROOT))
        self.assertTrue(h.allowed_subprocess(coverage_json, ROOT))
        self.assertFalse(h.allowed_subprocess([sys.executable, "-m", "coverage", "erase"], ROOT))
        with self.assertRaises(h.QualificationError):
            h._git(ROOT, "push")

    def test_static_scan_and_declared_dependency_inventory(self):
        result = h.static_scan(ROOT)
        self.assertTrue(result["passed"])
        self.assertEqual(result["reviewed_direct_dependencies"], {
            "hex": "0.4.3", "serde_json": "1.0.149", "sha2": "0.11.0"})

    def test_static_scan_rejects_each_authority_and_manifest_drift(self):
        mutations = (
            ("tools/native_theme/sq02-rust-qualifier/src/main.rs", lambda raw: raw + b"\nuse std::net;\n"),
            ("scripts/test-native-theme-sq02.py", lambda _raw: b"def broken(:\n"),
            ("scripts/test-native-theme-sq02.py", lambda raw: raw + b"\neval('1')\n"),
            ("scripts/test-native-theme-sq02.py", lambda raw: raw + b"\nsubprocess.run([], shell=True)\n"),
            ("tools/native_theme/sq02-rust-qualifier/Cargo.toml", lambda raw: raw.replace(b'hex = "=0.4.3"', b'hex = "=0.4.2"')),
            ("tools/native_theme/sq02-rust-qualifier/Cargo.toml", lambda raw: raw.replace(b"default = []", b'default = ["x"]')),
        )
        for relative, mutate in mutations:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td); copy_static_root(root); path = root / relative; path.write_bytes(mutate(path.read_bytes()))
                with self.assertRaises(h.QualificationError): h.static_scan(root)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); copy_static_root(root); (root / "tools/native_theme/sq02-rust-qualifier/build.rs").write_text("")
            with self.assertRaises(h.QualificationError): h.static_scan(root)

    def test_five_packages_are_full_file_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            rows, artifacts = h.build_packages(ROOT, Path(directory) / "packages")
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({row["id"] for row in rows}), 5)
        self.assertTrue(all(row["bytes"] > 0 and len(row["sha256"]) == 64 for row in rows))
        self.assertIn("catalog-index.json", artifacts)

    def test_exact_boundaries_and_layer_specific_plus_one(self):
        for size in (262143, 262144, 262145):
            raw = h.package_with_exact_length(ROOT, size)
            self.assertEqual(len(raw), size)
            contract = h.python_decode(ROOT, raw)
            compiler = h.python_decode(ROOT, raw, compiler_layer=True)
            if size <= 262144:
                self.assertTrue(contract["accepted"] and compiler["accepted"])
            else:
                self.assertEqual(contract["code"], "E_LIMIT_PACK")
                self.assertEqual(compiler["code"], "E_CANONICAL_SIZE")

    def test_python_diagnostics_are_stable(self):
        expected = {
            b'{"x":0}': "E_JSON_NONCANONICAL",
            b'{"x":NaN}\n': "E_NUMBER_NONFINITE",
            b'{"x":1,"x":2}\n': "E_JSON_DUPLICATE",
            b'{"x":"\xff"}\n': "E_UTF8",
        }
        for raw, code in expected.items():
            self.assertEqual(h.python_decode(ROOT, raw)["code"], code)

    def test_seeded_corpus_executes_all_operators_deterministically(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            first, first_blob = h.generate_corpus(ROOT, Path(left) / "corpus")
            second, second_blob = h.generate_corpus(ROOT, Path(right) / "corpus")
        self.assertEqual(h.canonical_json_bytes(first), h.canonical_json_bytes(second))
        self.assertEqual(first_blob, second_blob)
        self.assertEqual(len(first["cases"]), 256)
        self.assertEqual(len({row["id"] for row in first["cases"]}), 256)
        self.assertEqual(len({row["sha256"] for row in first["cases"]}), 256)
        self.assertEqual(Counter(row["mutation_operator"] for row in first["cases"]),
                         Counter({operator: 16 for operator in h.CORPUS_OPERATORS}))
        self.assertEqual(sum(row["python_accepted"] for row in first["cases"]), 32)
        mismatch = {row["mutation_operator"]: (row["python_code"], row["rust_code"])
                    for row in first["cases"] if row["python_code"] != row["rust_code"]}
        self.assertEqual(mismatch, {"hash-tamper": ("E_PROVENANCE", "E_HASH"),
                                    "provenance-tamper": ("E_PROVENANCE", "E_IDENTITY")})

    def test_output_and_source_fail_closed(self):
        with self.assertRaises(h.QualificationError):
            h.validate_output(ROOT, ROOT / "artifacts/quality/not-sq02")
        with self.assertRaises(h.QualificationError) as caught:
            h.source_identity(ROOT, ROOT / "artifacts/quality/sq-02", "f" * 40)
        self.assertEqual(caught.exception.classification, "CI_SOURCE_IDENTITY")
        dirty_responses = {("rev-parse", "HEAD"): "1" * 40 + "\n", ("rev-parse", "HEAD^{tree}"): "2" * 40 + "\n",
                           ("status", "--porcelain=v1", "--untracked-files=all"): " M tracked.py\n"}
        with mock.patch.object(h, "_git", side_effect=lambda _root, *args: dirty_responses[args]), \
             self.assertRaises(h.QualificationError) as caught:
            h.source_identity(ROOT, ROOT / "artifacts/quality/sq-02", "1" * 40)
        self.assertEqual(caught.exception.classification, "CI_SOURCE_DIRTY")
        responses = {("rev-parse", "HEAD"): "1" * 40 + "\n", ("rev-parse", "HEAD^{tree}"): "2" * 40 + "\n",
                     ("status", "--porcelain=v1", "--untracked-files=all"): "",
                     ("diff", "--name-only", f"{h.BASE_SHA}..{'1' * 40}"): "unexpected.txt\n"}
        with mock.patch.object(h, "_git", side_effect=lambda _root, *args: responses[args]):
            with self.assertRaises(h.QualificationError) as caught:
                h.source_identity(ROOT, ROOT / "artifacts/quality/sq-02", "1" * 40)
        self.assertEqual(caught.exception.classification, "CI_SOURCE_SCOPE")
        responses[ ("diff", "--name-only", f"{h.BASE_SHA}..{'1' * 40}") ] = ""
        with mock.patch.object(h, "_git", side_effect=lambda _root, *args: responses[args]):
            self.assertEqual(h.source_identity(ROOT, ROOT / "artifacts/quality/sq-02", "1" * 40), ("1" * 40, "2" * 40))
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td); (fake_root / "artifacts/quality").mkdir(parents=True)
            (fake_root / "artifacts/quality/sq-02").symlink_to(fake_root / "elsewhere")
            with self.assertRaises(h.QualificationError):
                h.validate_output(fake_root, fake_root / "artifacts/quality/sq-02")

    def test_two_git_archive_materializations_have_exact_tracked_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            h.materialize(ROOT, h.BASE_SHA, base / "a")
            h.materialize(ROOT, h.BASE_SHA, base / "b")
            relative = "tools/native_theme/native_theme_v1.py"
            self.assertEqual((base / "a" / relative).read_bytes(), (base / "b" / relative).read_bytes())
            self.assertEqual(h.sha256((base / "a" / relative).read_bytes()),
                             h.sha256((ROOT / relative).read_bytes()))

    def test_fuchsia_qualification_has_no_runtime_authority_edge(self):
        build = (ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_model/BUILD.gn").read_text()
        block = build[build.index('rustc_test("theme_model_qualification")'):]
        self.assertIn("testonly = true", block)
        self.assertIn('source_root = "src/qualification.rs"', block)
        qualification = (ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_model/src/qualification.rs").read_text()
        self.assertIn('const EXTENSIONS_MARKER: &[u8]', qualification)
        self.assertIn('br#""extensions":{"#', qualification)
        self.assertNotIn('serde_json::to_vec(&value)', qualification)
        for token in ("fuchsia_package", "fuchsia_component", "runtime_deps", "product_assembly"):
            self.assertNotIn(token, block)
        catalog = (ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_catalog/BUILD.gn").read_text()
        self.assertTrue(catalog.lstrip().startswith('copy("catalog_artifacts")'))

    def test_ci_prepares_before_isolated_gate_and_uploads_exact_eight(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        python_prepare = workflow.index("Prepare NativeThemeV1 sq-02 Python dependencies")
        rust_prepare = workflow.index("Prepare NativeThemeV1 sq-02 Rust toolchain")
        fetch = workflow.index("Prepare NativeThemeV1 sq-02 locked crates")
        gate = workflow.index("NativeThemeV1 sq-02 native Rust compiler packaging gate")
        upload = workflow.index("Upload NativeThemeV1 sq-02 receipts")
        self.assertLess(python_prepare, rust_prepare)
        self.assertLess(rust_prepare, fetch)
        self.assertLess(fetch, gate)
        self.assertLess(gate, upload)
        self.assertNotIn("self-hosted", workflow)
        upload_block = workflow[upload:workflow.index("Instrument Studio desktop_ui host contract")]
        self.assertEqual(sum(f"artifacts/quality/sq-02/{name}" in upload_block for name in h.RECEIPTS), 8)

    def test_rust_record_requirement_omission_is_rejected(self):
        cargo = Path("/bin/cargo")
        rustc = Path("/bin/rustc")
        record = {"requirement_ids": list(h.REQUIREMENT_IDS[:-1])}
        completed = __import__("subprocess").CompletedProcess([], 0,
            stdout="SQ02_RUST:" + json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", stderr="")
        with mock.patch.object(h, "run_allowed", return_value=completed), tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self.assertRaises(h.QualificationError):
                h.run_cargo(ROOT, cargo, rustc, base / "home", base / "target", base / "packages", base / "corpus")
        record = {"requirement_ids": list(h.REQUIREMENT_IDS)}
        completed = __import__("subprocess").CompletedProcess([], 0,
            stdout="SQ02_RUST:" + json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", stderr="")
        with mock.patch.object(h, "run_allowed", return_value=completed), tempfile.TemporaryDirectory() as td:
            base = Path(td)
            parsed, raw = h.run_cargo(ROOT, cargo, rustc, base / "home", base / "target", base / "packages", base / "corpus")
        self.assertEqual(parsed, record); self.assertTrue(raw.endswith(b"\n"))
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self.assertRaises(h.QualificationError):
                h.run_cargo(ROOT, cargo, rustc, Path("relative"), base / "target", base / "packages", base / "corpus")

    def test_binary_record_payload_authority_coverage_and_receipts(self):
        completed = __import__("subprocess").CompletedProcess([], 0, stdout="rustc 1.99.0-nightly\n", stderr="")
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "rustc"; tool.write_bytes(b"tool")
            with mock.patch.object(h, "run_allowed", return_value=completed):
                self.assertEqual(h._binary_record(tool, "rustc")["name"], "rustc")
            with mock.patch.object(h, "run_allowed", return_value=__import__("subprocess").CompletedProcess([], 0, stdout="stable\n", stderr="")):
                with self.assertRaises(h.QualificationError): h._binary_record(tool, "rustc")
            with self.assertRaises(h.QualificationError): h._binary_record(tool, "cargo")

        with tempfile.TemporaryDirectory() as td:
            base = Path(td); workspace = base / "payload"; package_dir = workspace / "packages"
            descriptor_path = base / "tools/native_theme/catalog/catalog-source.json"
            descriptor_path.parent.mkdir(parents=True); descriptor_path.write_bytes(b"{}\n")
            packages = payload_fixture()["packages"]
            artifacts = {"x.receipt.json": b"{}\n", "catalog-index.json": b"{}\n"}
            def packages_mock(_root, destination): destination.mkdir(parents=True); return packages, artifacts
            def corpus_mock(_root, destination):
                destination.mkdir(parents=True)
                cases = [{"mutation_operator": op, "python_accepted": True, "python_code": None,
                          "rust_accepted": True, "rust_code": None} for op in h.CORPUS_OPERATORS]
                return {"cases": cases}, b"corpus"
            rust = {"boundaries": [], "corpus": {"accepted": 1, "executed": 16, "rejected": 15},
                    "requirement_ids": list(h.REQUIREMENT_IDS)}
            with mock.patch.object(h, "static_scan", return_value={"passed": True}), \
                 mock.patch.object(h, "build_packages", side_effect=packages_mock), \
                 mock.patch.object(h, "strict_json", return_value={"template_path": "template", "entries": []}), \
                 mock.patch.object(h, "package_with_exact_length", side_effect=lambda _r, size: b"x" * size), \
                 mock.patch.object(h, "generate_corpus", side_effect=corpus_mock), \
                 mock.patch.object(h, "run_cargo", return_value=(rust, b"rust\n")), \
                 mock.patch.object(h, "python_decode", return_value={"accepted": True}):
                (base / "template").write_bytes(b"x")
                result = h.payload(base, workspace, Path("/bin/cargo"), Path("/bin/rustc"), base / "home", base / "target")
            self.assertEqual(len(result["diagnostic_mapping"]), 16)

        with mock.patch.object(h, "_git", side_effect=lambda _root, *args: ""), tempfile.TemporaryDirectory() as td:
            scan = h.authority_scan(ROOT, {})
        self.assertTrue(scan["catalog_copy_only"])

        with tempfile.TemporaryDirectory() as td:
            base = Path(td); workspace = base / "coverage"
            source_rows = {}
            import ast
            for relative in ("tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py"):
                tree = ast.parse((ROOT / relative).read_bytes()); lines = list(range(1, 2000))
                source_rows[str(ROOT / relative)] = {"executed_lines": lines, "summary": {"covered_branches": 1,
                    "num_branches": 1, "covered_lines": 1, "num_statements": 1}}
            calls = {"count": 0}
            def coverage_run(_argv, _root, **_kwargs):
                calls["count"] += 1
                if calls["count"] == 3:
                    (workspace / "coverage-machine.json").write_text(json.dumps({"files": source_rows}))
                return __import__("subprocess").CompletedProcess([], 0, stdout="", stderr="")
            with mock.patch.object(h, "run_allowed", side_effect=coverage_run):
                metrics, artifact = h.measure_coverage(ROOT, workspace)
            self.assertEqual(len(metrics), 2); self.assertEqual(len(artifact), 64)

        first = payload_fixture(); second = copy = json.loads(json.dumps(first))
        metric = {name: {"branches_covered": 1, "branches_total": 1, "functions_with_body_execution": 1,
                         "functions_total": 1, "statements_covered": 1, "statements_total": 1}
                  for name in ("tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py")}
        scan = {"audited_authority_files": [], "bounded_lexical_scan": True, "catalog_copy_only": True,
                "catalog_entry_count": 4, "changed_files_scanned": 1, "findings": [], "fuchsia_forbidden_edges": [],
                "qualification_testonly": True, "receipts_scanned": 8, "tracked_files_considered": 1}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h.importlib.metadata, "version", side_effect=lambda name: h.PINNED[name]), \
             mock.patch.object(h, "_binary_record", side_effect=lambda _p, name: {"binary_sha256": "0" * 64, "name": name, "version": f"{name} 1.99.0-nightly"}), \
             mock.patch.object(h, "_tracked_hashes", return_value={}), mock.patch.object(h, "authority_scan", return_value=scan), \
             mock.patch.dict(os.environ, {"NATIVE_THEME_SQ02_TOOLCHAIN_ORIGIN": "project-fuchsia-prebuilt"}):
            receipts = h.write_receipts(ROOT, Path(td) / "out", "1" * 40, "2" * 40, {}, Path("/bin/cargo"),
                                        Path("/bin/rustc"), first, second, metric, "9" * 64)
        self.assertEqual(len(receipts), 8)

    def test_remaining_internal_fail_closed_branches(self):
        responses = {("rev-parse", "HEAD"): "1" * 40 + "\n", ("rev-parse", "HEAD^{tree}"): "2" * 40 + "\n",
                     ("status", "--porcelain=v1", "--untracked-files=all"): "",
                     ("diff", "--name-only", f"{h.BASE_SHA}..{'1' * 40}"): ""}
        with mock.patch.object(h, "_git", side_effect=lambda _root, *args: responses[args]):
            self.assertEqual(h.source_identity(ROOT, Path("/outside"), "1" * 40), ("1" * 40, "2" * 40))
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(h.QualificationError): h.validate_output(ROOT, ROOT / "artifacts/quality/sq-02")
        self.assertEqual(h.validate_output(ROOT, ROOT / "artifacts/quality/sq-02"),
                         (ROOT / "artifacts/quality/sq-02").resolve())

        h._PRODUCTION_CACHE.pop(str(ROOT.resolve()), None)
        sys.modules["adapters.synthetic"] = object()
        h._load_production(ROOT)
        self.assertNotIn("adapters.synthetic", sys.modules)

        class FakeContract:
            LIMITS = {"string_bytes": 4096, "compiled_pack_bytes": 262144}
            class ContractError(ValueError): pass
            @staticmethod
            def canonical_json_bytes(value): return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            @staticmethod
            def validate_package(_value): pass
            @staticmethod
            def package_semantic_identity(_value): return "sha256:" + "1" * 64
        class FakeCatalog:
            @staticmethod
            def generate_catalog(descriptor, _supplied):
                return {f"{row['id']}.package.json": b"{}\n" for row in descriptor["entries"]}
        descriptor = json.loads((ROOT / "tools/native_theme/catalog/catalog-source.json").read_text())
        descriptor["entries"] = descriptor["entries"][:3]
        real_strict = h.strict_json
        with mock.patch.object(h, "_load_production", return_value=(FakeCatalog, FakeContract)), \
             mock.patch.object(h, "strict_json", side_effect=lambda raw: descriptor if b'"budgets"' in raw else {}), \
             tempfile.TemporaryDirectory() as td:
            with self.assertRaises(h.QualificationError): h.build_packages(ROOT, Path(td) / "packages")
        with self.assertRaises(h.QualificationError): h.package_with_exact_length(ROOT, 1)
        fake_calls = {"n": 0}
        def short_canonical(_value):
            fake_calls["n"] += 1
            return b"a" if fake_calls["n"] == 1 else b"b"
        with mock.patch.object(h, "_load_production", return_value=(None, FakeContract)), \
             mock.patch.object(FakeContract, "canonical_json_bytes", side_effect=short_canonical), \
             mock.patch.object(h, "strict_json", return_value={"metadata": {"extensions": {}}}):
            with self.assertRaises(h.QualificationError): h.package_with_exact_length(ROOT, 100)

        raw = b'{"metadata":{"provenance":{"semantic_hash":"declared"}}}\n'
        with mock.patch.object(h, "_load_production", return_value=(None, FakeContract)):
            self.assertEqual(h.python_decode(ROOT, raw)["code"], "E_HASH")
        self.assertEqual(h.python_decode(ROOT, b"{]\n")["code"], "E_JSON_MALFORMED")

        with tempfile.TemporaryDirectory() as td, mock.patch.object(h, "sha256", return_value="0" * 64):
            with self.assertRaises(h.QualificationError): h.generate_corpus(ROOT, Path(td) / "corpus")
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h, "CORPUS_OPERATORS", ("valid-inert-metadata",)):
            with self.assertRaises(h.QualificationError): h.generate_corpus(ROOT, Path(td) / "corpus")

        completed = __import__("subprocess").CompletedProcess([], 0, stdout="noise\n", stderr="")
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h, "run_allowed", return_value=completed):
            base = Path(td)
            with self.assertRaises(h.QualificationError):
                h.run_cargo(ROOT, Path("/bin/cargo"), Path("/bin/rustc"), base / "home", base / "target", base / "p", base / "c")

        with tempfile.TemporaryDirectory() as td:
            fake = Path(td); (fake / "overlays/fuchsia/src/fuchsia-desktop/theme_model").mkdir(parents=True)
            (fake / "overlays/fuchsia/src/fuchsia-desktop/theme_catalog").mkdir(parents=True)
            (fake / "tools/native_theme/catalog").mkdir(parents=True)
            (fake / "overlays/fuchsia/src/fuchsia-desktop/theme_model/BUILD.gn").write_text('rustc_test("theme_model_qualification") { fuchsia_package = true }')
            (fake / "overlays/fuchsia/src/fuchsia-desktop/theme_catalog/BUILD.gn").write_text("other() {}")
            (fake / "tools/native_theme/catalog/catalog-source.json").write_bytes(b'{"entries":[]}\n')
            (fake / "clean.py").write_text("pass\n"); (fake / "private.py").write_bytes(b"/" + b"home/example")
            (fake / "badlink").symlink_to(fake / "clean.py")
            def fake_git(_root, *args):
                return "tracked\n" if args == ("ls-files",) else "badlink\nclean.py\nprivate.py\n"
            with mock.patch.object(h, "_git", side_effect=fake_git):
                scan = h.authority_scan(fake, {"receipt.json": b"/" + b"home/example"})
            self.assertGreaterEqual(len(scan["findings"]), 3)
            with mock.patch.object(h, "_git", side_effect=fake_git):
                h.authority_scan(fake, {"clean-receipt.json": b"{}\n"})

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            failure = __import__("subprocess").CompletedProcess([], 1, stdout="", stderr="")
            with mock.patch.object(h, "run_allowed", return_value=failure):
                with self.assertRaises(h.QualificationError): h.measure_coverage(ROOT, base / "one")
            calls = iter([__import__("subprocess").CompletedProcess([], 0), __import__("subprocess").CompletedProcess([], 0), failure])
            with mock.patch.object(h, "run_allowed", side_effect=lambda *_a, **_k: next(calls)):
                with self.assertRaises(h.QualificationError): h.measure_coverage(ROOT, base / "two")
            calls_count = {"n": 0}
            def missing_report(_argv, _root, **_kwargs):
                calls_count["n"] += 1
                if calls_count["n"] == 3: (base / "three/coverage-machine.json").write_text('{"files":{}}')
                return __import__("subprocess").CompletedProcess([], 0)
            with mock.patch.object(h, "run_allowed", side_effect=missing_report):
                with self.assertRaises(h.QualificationError): h.measure_coverage(ROOT, base / "three")
            gap_workspace = base / "four"; gap_calls = {"n": 0}
            gap_files = {str(ROOT / relative): {"executed_lines": [], "summary": {"covered_branches": 0,
                "num_branches": 1, "covered_lines": 0, "num_statements": 1}}
                for relative in ("tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py")}
            def gap_report(_argv, _root, **_kwargs):
                gap_calls["n"] += 1
                if gap_calls["n"] == 3: (gap_workspace / "coverage-machine.json").write_text(json.dumps({"files": gap_files}))
                return __import__("subprocess").CompletedProcess([], 0)
            with mock.patch.object(h, "run_allowed", side_effect=gap_report):
                with self.assertRaises(h.QualificationError): h.measure_coverage(ROOT, gap_workspace)
        self.assertTrue(h._tracked_hashes(ROOT))

        first = payload_fixture(); second = json.loads(json.dumps(first)); second["catalog"] = {}
        metric = {name: {"branches_covered": 1, "branches_total": 1, "functions_with_body_execution": 1,
                         "functions_total": 1, "statements_covered": 1, "statements_total": 1}
                  for name in ("tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py")}
        common = (mock.patch.object(h.importlib.metadata, "version", side_effect=lambda name: h.PINNED[name]),
                  mock.patch.object(h, "_binary_record", return_value={"binary_sha256": "0" * 64, "name": "cargo", "version": "1.99.0-nightly"}),
                  mock.patch.object(h, "_tracked_hashes", return_value={}))
        with tempfile.TemporaryDirectory() as td, common[0], common[1], common[2]:
            with self.assertRaises(h.QualificationError):
                h.write_receipts(ROOT, Path(td) / "out", "1" * 40, "2" * 40, {}, Path("/bin/cargo"), Path("/bin/rustc"), first, second, metric, "9" * 64)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h.importlib.metadata, "version", return_value="bad"):
            with self.assertRaises(h.QualificationError):
                h.write_receipts(ROOT, Path(td) / "out", "1" * 40, "2" * 40, {}, Path("/bin/cargo"), Path("/bin/rustc"), first, first, metric, "9" * 64)
        binary = {"binary_sha256": "0" * 64, "name": "tool", "version": "1.99.0-nightly"}
        bad_scan = {"findings": [{"code": "E"}], "fuchsia_forbidden_edges": [], "qualification_testonly": True}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h.importlib.metadata, "version", side_effect=lambda name: h.PINNED[name]), \
             mock.patch.object(h, "_binary_record", return_value=binary), mock.patch.object(h, "_tracked_hashes", return_value={}), \
             mock.patch.object(h, "authority_scan", return_value=bad_scan):
            with self.assertRaises(h.QualificationError):
                h.write_receipts(ROOT, Path(td) / "out", "1" * 40, "2" * 40, {}, Path("/bin/cargo"), Path("/bin/rustc"), first, first, metric, "9" * 64)
        private_first = json.loads(json.dumps(first)); private_first["catalog"] = {"/" + "home/example": {"bytes": 1, "sha256": "0" * 64}}
        good_scan = {"findings": [], "fuchsia_forbidden_edges": [], "qualification_testonly": True}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h.importlib.metadata, "version", side_effect=lambda name: h.PINNED[name]), \
             mock.patch.object(h, "_binary_record", return_value=binary), mock.patch.object(h, "_tracked_hashes", return_value={}), \
             mock.patch.object(h, "authority_scan", return_value=good_scan):
            with self.assertRaises(h.QualificationError):
                h.write_receipts(ROOT, Path(td) / "out", "1" * 40, "2" * 40, {}, Path("/bin/cargo"), Path("/bin/rustc"), private_first, private_first, metric, "9" * 64)

        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo("../bad"); info.size = 0; archive.addfile(info)
        completed = __import__("subprocess").CompletedProcess([], 0, stdout=stream.getvalue(), stderr=b"")
        with tempfile.TemporaryDirectory() as td, mock.patch.object(h, "run_allowed", return_value=completed):
            with self.assertRaises(h.QualificationError): h.materialize(ROOT, "1" * 40, Path(td) / "archive")

    def test_top_level_run_orchestration_and_failures(self):
        isolation = {"namespace_changed": True}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); output = base / "out"; target = base / "target"
            fixed = {**h.ENVIRONMENT, "NATIVE_THEME_SQ02_NAMESPACE_PROVED": "true"}
            undo = mock.Mock()
            with mock.patch.dict(os.environ, fixed, clear=True), \
                 mock.patch.object(h, "validate_output", return_value=output), \
                 mock.patch.object(h, "source_identity", side_effect=[("1" * 40, "2" * 40), ("1" * 40, "2" * 40)]), \
                 mock.patch.object(h, "static_scan"), mock.patch.object(h, "install_python_network_denial", return_value=undo), \
                 mock.patch.object(h, "materialize", side_effect=lambda _r, _s, d: d.mkdir()), \
                 mock.patch.object(h, "payload", return_value=payload_fixture()), \
                 mock.patch.object(h, "measure_coverage", return_value=({}, "0" * 64)), \
                 mock.patch.object(h, "write_receipts", return_value={"x": b"y"}), \
                 mock.patch("sq02_receipt_verifier.verify_directory"):
                result = h.run(ROOT, "1" * 40, output, Path("/bin/cargo"), Path("/bin/rustc"), base / "home", target, isolation)
            self.assertEqual(result, {"x": b"y"}); undo.assert_called_once()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(h.QualificationError):
                h.run(ROOT, "1" * 40, Path("x"), Path("c"), Path("r"), Path("h"), Path("t"), isolation)
        bad_env = {**h.ENVIRONMENT, "NATIVE_THEME_SQ02_NAMESPACE_PROVED": "true", "TZ": "local"}
        with mock.patch.dict(os.environ, bad_env, clear=True):
            with self.assertRaises(h.QualificationError):
                h.run(ROOT, "1" * 40, Path("x"), Path("c"), Path("r"), Path("h"), Path("t"), isolation)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); fixed = {**h.ENVIRONMENT, "NATIVE_THEME_SQ02_NAMESPACE_PROVED": "true"}
            with mock.patch.dict(os.environ, fixed, clear=True), mock.patch.object(h, "validate_output", return_value=base / "out"), \
                 mock.patch.object(h, "source_identity", side_effect=[("1" * 40, "2" * 40), ("3" * 40, "4" * 40)]), \
                 mock.patch.object(h, "static_scan"), mock.patch.object(h, "install_python_network_denial", return_value=lambda: None), \
                 mock.patch.object(h, "materialize", side_effect=lambda _r, _s, d: d.mkdir()), \
                 mock.patch.object(h, "payload", return_value=payload_fixture()), mock.patch.object(h, "measure_coverage", return_value=({}, "0" * 64)), \
                 mock.patch.object(h, "write_receipts", return_value={}), mock.patch("sq02_receipt_verifier.verify_directory"):
                with self.assertRaises(h.QualificationError):
                    h.run(ROOT, "1" * 40, base / "out", Path("/bin/cargo"), Path("/bin/rustc"), base / "home", base / "target", isolation)

    def test_missing_offline_crates_classifies_infrastructure(self):
        completed = __import__("subprocess").CompletedProcess([], 101, stdout="", stderr="no matching package named x")
        with mock.patch.object(h, "run_allowed", return_value=completed), tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self.assertRaises(h.QualificationError) as caught:
                h.run_cargo(ROOT, Path("/bin/cargo"), Path("/bin/rustc"), base / "home", base / "target", base / "packages", base / "corpus")
        self.assertEqual(caught.exception.classification, "CI_TOOLCHAIN_INFRASTRUCTURE")


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = launcher_module()

    def test_launcher_static_scan_and_command_allowlist(self):
        self.launcher.static_scan(ROOT)
        self.assertTrue(self.launcher.allowed_launcher_command(
            ["/usr/bin/unshare", "-Urn", "--", "/usr/bin/true"], phase="selection"))
        self.assertTrue(self.launcher.allowed_launcher_command(
            [sys.executable, "-I", "-S", "-c", self.launcher.PROBE], phase="socket-probe"))
        for command in (["curl", "example"], [sys.executable, "-c", "pass"]):
            self.assertFalse(self.launcher.allowed_launcher_command(command, phase="socket-probe"))

    def test_unprivileged_selection_precedes_ci_sudo(self):
        success = __import__("subprocess").CompletedProcess([], 0)
        with mock.patch.object(self.launcher, "run_allowed", return_value=success) as run:
            mode, prefix = self.launcher.choose_namespace()
        self.assertEqual(mode, "unprivileged-user-network")
        self.assertIn("-Urn", prefix)
        self.assertEqual(run.call_count, 1)

    def test_ci_sudo_fallback_and_total_failure_are_stable(self):
        failure = __import__("subprocess").CompletedProcess([], 1)
        success = __import__("subprocess").CompletedProcess([], 0)
        with mock.patch.dict(__import__("os").environ, {"GITHUB_ACTIONS": "true"}), \
             mock.patch.object(self.launcher, "run_allowed", side_effect=[failure, success]), \
             mock.patch.object(self.launcher.shutil, "which", side_effect=lambda name, path=None: f"/usr/bin/{name}"):
            mode, prefix = self.launcher.choose_namespace()
        self.assertEqual(mode, "ci-sudo-network")
        self.assertEqual(Path(prefix[0]).name, "sudo")
        with mock.patch.dict(__import__("os").environ, {}, clear=True), \
             mock.patch.object(self.launcher, "run_allowed", return_value=failure):
            with self.assertRaises(RuntimeError):
                self.launcher.choose_namespace()

    def test_namespace_identity_is_compared_not_emitted(self):
        with mock.patch.object(self.launcher.os, "readlink", return_value="net:[123]"):
            self.assertEqual(self.launcher.namespace_identity(), "net:[123]")
        with mock.patch.object(self.launcher.os, "readlink", return_value="bad"):
            with self.assertRaises(RuntimeError):
                self.launcher.namespace_identity()


if __name__ == "__main__":
    unittest.main(verbosity=2)
