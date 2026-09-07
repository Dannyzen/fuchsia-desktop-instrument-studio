# P3-S3 native theme lifecycle diagnostics

P3-S3 adds a bounded Inspect collection and a deterministic machine receipt for restart-time theme lifecycle evidence. The stable codes, rather than messages, are the contract. Settings remains restart-only: staging a selection, restore, or migration never activates or republishes a snapshot in the running process.

The `native_theme` Inspect node retains these fixed fields: `schema_version`, `active_theme_id`, `selected_theme_id`, `fallback_theme_id`, `last_known_good_theme_id`, `theme_revision`, `theme_variant`, `semantic_sha256_prefix`, `generation`, `validation_result_code`, `selection_source`, `selection_error_code`, `consumer_ack_count`, `last_ack_generation`, `elapsed_micros`, `resource_result_code`, and `last_receipt`.

The schema version is 1. Codes are at most 32 bytes, identifiers at most 64 bytes, the semantic hash prefix represents 8 hash bytes, and the complete machine receipt is at most 1280 bytes. The receipt is fixed-field JSON in the field order above. It contains no payload bytes, no arbitrary paths, no canonical packages, and no arbitrary runtime error text.

Journey codes are `crash`, `restart`, `corrupt-state`, `invalid-theme`, `stale-consumer`, `recovery`, and `shell-survival`. Event codes are `startup-active`, `startup-recovered`, `selection-staged`, `restore-staged`, `migration-staged`, `lkg-recorded`, `consumer-ack`, `consumer-stale`, `process-crash`, `recovery-complete`, and `shell-survived`. Each receipt is also emitted under the stable `native_theme_lifecycle` log target with the `NATIVE_THEME_LIFECYCLE_RECEIPT` marker. Result codes are `ok`, `recovered`, `rejected`, `storage-error`, and `not-served`. Existing bounded selection-source and validation codes remain code-only inputs.

Collection occurs at startup recovery/activation, after Settings operations produce their existing result and exact correlated state, when WatchCurrent carries a consumer-supplied observed generation, when duplicate watch behavior closes with BAD_STATE, and after ServiceFs successfully serves the outgoing directory. GetCurrent sends a snapshot but does not claim a consumer acknowledgement. Shell survival only proves that outgoing-directory milestone; it does not claim a complete live journey.

The live Fuchsia proof remains pending. P4 repaint remains pending.

## Crash and repair receipts

The service installs a bounded panic hook. A Rust panic emits the `crash` / `process-crash` receipt without embedding panic payload text or paths. This is source wiring for panic failures, not proof of every termination mode.

When startup selected fallback because persisted state or a selected identity was invalid, the next successful Settings repair emits `recovery` / `recovery-complete`. Corrupt-state and invalid-theme startup receipts remain distinct from the later repair-complete receipt. Live Fuchsia crash, restart, and repair journeys remain separately approval-gated and unproven here.
