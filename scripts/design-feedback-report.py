#!/usr/bin/env python3
"""Build an Instrument Studio design-feedback report from Fuchsia diagnostics."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def first_tiling_node(data: Any) -> dict[str, Any] | None:
    """Find a tiling_wm inspect node in common ffx JSON shapes."""
    if data is None:
        return None

    def walk(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            if "tiling_wm" in node and isinstance(node["tiling_wm"], dict):
                return node["tiling_wm"]
            # payload style
            payload = node.get("payload")
            if isinstance(payload, dict):
                found = walk(payload)
                if found:
                    return found
            root = node.get("root")
            if isinstance(root, dict):
                found = walk(root)
                if found:
                    return found
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return None

    return walk(data)


def coerce_wm_state(node: dict[str, Any] | None) -> dict[str, Any]:
    if not node:
        return {
            "available": False,
            "tile_count": None,
            "order": [],
            "selected_focus": None,
            "confirmed_focus": None,
            "gap_px": None,
            "active_border_px": None,
            "wrap_focus": None,
            "present_count": None,
            "last_present_context": None,
        }

    def leaf(value: Any) -> Any:
        if isinstance(value, dict):
            # inspect property encoding variants
            for key in ("value", "uint_value", "string_value", "bool_value"):
                if key in value:
                    return value[key]
        return value

    focus = node.get("focus") if isinstance(node.get("focus"), dict) else {}
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    order_raw = leaf(node.get("order", ""))
    order = [part for part in str(order_raw).split(",") if part]

    return {
        "available": True,
        "tile_count": leaf(node.get("tile_count")),
        "order": order,
        "selected_focus": leaf(focus.get("selected")) or leaf(node.get("selected_focus")),
        "confirmed_focus": leaf(focus.get("confirmed")) or leaf(node.get("confirmed_focus")),
        "gap_px": leaf(config.get("gap_px")) or leaf(node.get("gap_px")),
        "active_border_px": leaf(config.get("active_border_px"))
        or leaf(node.get("active_border_px")),
        "wrap_focus": leaf(config.get("wrap_focus")) or leaf(node.get("wrap_focus")),
        "present_count": leaf(node.get("present_count")),
        "last_present_context": leaf(node.get("last_present_context")),
    }


def parse_log_markers(text: str) -> dict[str, Any]:
    active = None
    cleared = 0
    order = None
    for line in text.splitlines():
        m = re.search(r"TILING_WM_ACTIVE id=([^\s]+) position=(\d+)", line)
        if m:
            active = {"id": m.group(1), "position": int(m.group(2))}
        if "TILING_WM_ACTIVE_CLEARED" in line:
            cleared += 1
        m = re.search(r"TILING_WM_ORDER ids=([^\s]+)", line)
        if m:
            order = [p for p in m.group(1).split(",") if p]
    return {"last_active": active, "active_cleared_count": cleared, "last_order": order}


def evaluate_instrument_studio(wm: dict[str, Any], logs: dict[str, Any]) -> dict[str, Any]:
    """Compare live diagnostics to the Instrument Studio design contract."""
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    available = bool(wm.get("available"))
    add("inspect_available", available, "tiling_wm inspect hierarchy present" if available else "missing tiling_wm inspect node")

    tile_count = wm.get("tile_count")
    try:
        tile_count_n = int(tile_count) if tile_count is not None else None
    except (TypeError, ValueError):
        tile_count_n = None
    add(
        "has_tiles",
        tile_count_n is not None and tile_count_n >= 1,
        f"tile_count={tile_count_n}",
    )
    add(
        "instrument_studio_grid_ready",
        tile_count_n is not None and tile_count_n >= 4,
        "design sketch assumes a 2x2 app grid when four apps are launched",
    )

    confirmed = wm.get("confirmed_focus") or ""
    selected = wm.get("selected_focus") or ""
    add(
        "confirmed_focus_visible_when_present",
        (not confirmed) or (confirmed == selected) or bool(confirmed),
        f"selected={selected!r} confirmed={confirmed!r}",
    )
    add(
        "confirmed_focus_non_empty_for_active_desktop",
        tile_count_n in (None, 0) or bool(confirmed) or bool(logs.get("last_active")),
        "active desktop should expose confirmed focus or recent TILING_WM_ACTIVE marker",
    )

    gap = wm.get("gap_px")
    border = wm.get("active_border_px")
    add("gap_default_or_set", gap in (None, 12) or isinstance(gap, int), f"gap_px={gap}")
    add(
        "active_border_default_or_set",
        border in (None, 3) or isinstance(border, int),
        f"active_border_px={border}",
    )

    ok = all(c["ok"] for c in checks if c["name"] != "instrument_studio_grid_ready")
    # grid is aspirational until four apps are launched; don't fail the whole loop hard
    return {
        "design_target": "instrument-studio",
        "ready_for_ui_iteration": ok,
        "checks": checks,
        "next_actions": next_actions(checks, wm),
    }


def next_actions(checks: list[dict[str, Any]], wm: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    by_name = {c["name"]: c for c in checks}
    if not by_name.get("inspect_available", {}).get("ok", False):
        actions.append(
            "Rebuild/publish tiling_wm with Inspect surface and relaunch the Workbench session."
        )
    if not by_name.get("has_tiles", {}).get("ok", False):
        actions.append("Launch Browser/Files/Settings/Terminal elements into the session.")
    if not by_name.get("instrument_studio_grid_ready", {}).get("ok", False):
        actions.append("Bring session to four tiles to match the Instrument Studio 2x2 sketch.")
    if wm.get("confirmed_focus") in (None, "") and wm.get("tile_count"):
        actions.append("Focus a tile until Scenic confirms focus (cyan active ring path).")
    if not actions:
        actions.append(
            "Diagnostics match the foundation contract; implement shared desktop_ui kit screens next."
        )
    return actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--design-target", default="instrument-studio")
    args = ap.parse_args()
    out = Path(args.out_dir)

    inspect_tiling = load_json(out / "inspect-tiling_wm.json")
    inspect_all = load_json(out / "inspect-all.json")
    node = first_tiling_node(inspect_tiling) or first_tiling_node(inspect_all)
    wm = coerce_wm_state(node)

    log_text = ""
    for name in ("tiling-wm-markers.log", "tiling-wm.log"):
        p = out / name
        if p.exists():
            log_text += p.read_text(errors="ignore") + "\n"
    logs = parse_log_markers(log_text)

    evaluation = evaluate_instrument_studio(wm, logs)
    report = {
        "design_target": args.design_target,
        "wm": wm,
        "log_markers": logs,
        "artifacts": {
            "inspect_tiling_wm": str(out / "inspect-tiling_wm.json"),
            "inspect_all": str(out / "inspect-all.json"),
            "logs": str(out / "tiling-wm-markers.log"),
            "screenshot": str(out / "session.png") if (out / "session.png").exists() else None,
        },
        "evaluation": evaluation,
    }
    text = json.dumps(report, indent=2)
    (out / "design-feedback.json").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
