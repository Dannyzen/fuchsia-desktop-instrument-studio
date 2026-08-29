#!/usr/bin/env python3
"""P3-S3 bounded lifecycle diagnostics architecture contract."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_service"
DIAGNOSTICS = SERVICE / "src/diagnostics.rs"
AUTHORITY = SERVICE / "src/authority.rs"
MAIN = SERVICE / "src/main.rs"
BUILD = SERVICE / "BUILD.gn"
DOC = ROOT / "docs/native-theme-lifecycle-diagnostics.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class NativeThemeP3S3Contract(unittest.TestCase):
    def test_01_diagnostics_is_a_generated_host_tested_module(self) -> None:
        self.assertTrue(DIAGNOSTICS.is_file(), "P3-S3 requires src/diagnostics.rs")
        build = text(BUILD)
        self.assertIn('"src/diagnostics.rs"', build)
        self.assertIn('with_unit_tests = true', build)

    def test_02_schema_and_all_bounds_are_explicit(self) -> None:
        source = text(DIAGNOSTICS)
        required = (
            "DIAGNOSTICS_SCHEMA_VERSION",
            "MAX_DIAGNOSTIC_CODE_BYTES",
            "MAX_DIAGNOSTIC_ID_BYTES",
            "SEMANTIC_HASH_PREFIX_BYTES",
            "MAX_RECEIPT_BYTES",
        )
        for symbol in required:
            self.assertIn(symbol, source)

    def test_03_all_required_journeys_have_stable_codes(self) -> None:
        source = text(DIAGNOSTICS)
        required = (
            "JOURNEY_CRASH",
            "JOURNEY_RESTART",
            "JOURNEY_CORRUPT_STATE",
            "JOURNEY_INVALID_THEME",
            "JOURNEY_STALE_CONSUMER",
            "JOURNEY_RECOVERY",
            "JOURNEY_SHELL_SURVIVAL",
            "EVENT_STARTUP_ACTIVE",
            "EVENT_STARTUP_RECOVERED",
            "EVENT_SELECTION_STAGED",
            "EVENT_RESTORE_STAGED",
            "EVENT_MIGRATION_STAGED",
            "EVENT_CONSUMER_ACK",
            "EVENT_CONSUMER_STALE",
            "RESULT_OK",
            "RESULT_RECOVERED",
            "RESULT_REJECTED",
            "RESULT_STORAGE_ERROR",
        )
        for symbol in required:
            self.assertIn(symbol, source)

    def test_04_receipt_has_bounded_machine_fields_not_payloads_or_paths(self) -> None:
        source = text(DIAGNOSTICS)
        for field in (
            "schema_version",
            "journey_code",
            "event_code",
            "result_code",
            "active_theme_id",
            "selected_theme_id",
            "fallback_theme_id",
            "last_known_good_theme_id",
            "theme_revision",
            "theme_variant",
            "semantic_sha256_prefix",
            "generation",
            "validation_result_code",
            "selection_source",
            "selection_error_code",
            "consumer_ack_count",
            "last_ack_generation",
            "elapsed_micros",
            "resource_result_code",
        ):
            self.assertIn(field, source)
        for forbidden in ("canonical_package", "payload_bytes", "state_path", "local_path"):
            self.assertNotIn(forbidden, source)
        self.assertIn("machine_receipt", source)

    def test_05_receipts_and_identifiers_are_actually_bounded(self) -> None:
        source = text(DIAGNOSTICS)
        for test_name in (
            "receipt_is_deterministic_and_bounded",
            "identifiers_are_bounded",
            "receipt_never_contains_payload_or_path",
            "receipt_max_values_are_json_safe_and_bounded",
            "recovery_is_distinct_from_normal_activation",
        ):
            self.assertIn(test_name, source)

    def test_06_inspect_surface_records_required_state(self) -> None:
        source = text(DIAGNOSTICS)
        for key in (
            '"schema_version"',
            '"active_theme_id"',
            '"selected_theme_id"',
            '"fallback_theme_id"',
            '"last_known_good_theme_id"',
            '"theme_revision"',
            '"theme_variant"',
            '"semantic_sha256_prefix"',
            '"generation"',
            '"validation_result_code"',
            '"selection_source"',
            '"selection_error_code"',
            '"consumer_ack_count"',
            '"last_ack_generation"',
            '"elapsed_micros"',
            '"resource_result_code"',
            '"last_receipt"',
        ):
            self.assertIn(key, source)

    def test_07_settings_results_update_diagnostics_without_hot_activation(self) -> None:
        authority = text(AUTHORITY)
        for method in (
            "record_selection_result",
            "record_restore_result",
            "record_migration_result",
            "record_last_known_good_result",
        ):
            self.assertIn(method, authority)
        self.assertIn("Arc<Diagnostics>", authority)
        # P3-S3 observes restart intent. It must not introduce an in-process activation method.
        self.assertNotIn("activate_selected_theme", authority)
        self.assertNotIn("publish_selected_snapshot", authority)

    def test_08_consumer_ack_and_stale_paths_are_runtime_wired(self) -> None:
        authority = text(AUTHORITY)
        self.assertIn("record_consumer_ack", authority)
        self.assertIn("record_consumer_stale", authority)
        self.assertIn("serve_native_theme", authority)

    def test_09_service_retains_shared_live_diagnostics(self) -> None:
        main = text(MAIN)
        self.assertIn("Arc::new(Diagnostics::record", main)
        self.assertIn("diagnostics.clone()", main)
        self.assertIn("record_shell_survival", main)

    def test_10_operator_contract_names_limits_and_claim_boundaries(self) -> None:
        self.assertTrue(DOC.is_file(), "P3-S3 requires an operator-facing diagnostics contract")
        doc = text(DOC)
        for phrase in (
            "P3-S3",
            "machine receipt",
            "stable codes",
            "no payload bytes",
            "no arbitrary paths",
            "restart-only",
            "live Fuchsia proof remains pending",
            "P4 repaint remains pending",
        ):
            self.assertIn(phrase, doc)

    def test_11_structured_log_receipts_use_a_stable_bounded_target(self) -> None:
        diagnostics = text(DIAGNOSTICS)
        main = text(MAIN)
        build = text(BUILD)
        for symbol in (
            "EVENT_PROCESS_CRASH",
            "EVENT_RECOVERY_COMPLETE",
            "EVENT_SHELL_SURVIVED",
            "NATIVE_THEME_LIFECYCLE_RECEIPT",
            "log::info!",
        ):
            self.assertIn(symbol, diagnostics)
        self.assertIn("#[fuchsia::main(logging = true)]", main)
        self.assertIn('"//third_party/rust_crates:log"', build)


    def test_12_review_blocker_contracts_are_production_wired(self):
        for symbol in (
            "RESULT_NOT_SERVED",
            "ALL_RESULT_CODES",
            "install_process_crash_hook",
            "finish_recovery_if_needed",
            "record_consumer_ack(observed_generation)",
            "select_with_post_store_hook_for_test",
            "receipt_history_for_test",
        ):
            self.assertIn(symbol, DIAGNOSTICS.read_text() + AUTHORITY.read_text() + MAIN.read_text())
        self.assertIn("not-served", DOC.read_text())
        self.assertIn("panic", DOC.read_text().lower())
        self.assertIn("repair", DOC.read_text().lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
