#!/usr/bin/env python3
"""Host contract: tile identity short labels and 4-app inspect gate."""


def short_label(tile_id: str) -> str:
    key = tile_id.lower()
    if "settings" in key:
        return "SET"
    if "files" in key:
        return "FIL"
    if "browser" in key:
        return "BRW"
    if "terminal" in key:
        return "TRM"
    return "APP"


def four_app_gate(tile_count: int, running: dict[str, bool]) -> bool:
    return tile_count == 4 and all(running.get(k) for k in ("settings", "files", "browser", "terminal"))


def main() -> int:
    assert short_label("tid-settings-1") == "SET"
    assert short_label("gr3-settings-20260819T231211Z") == "SET"
    assert short_label("tid-files-1") == "FIL"
    assert short_label("tid-browser-1") == "BRW"
    assert short_label("tid-terminal-1") == "TRM"
    assert four_app_gate(4, dict(settings=True, files=True, browser=True, terminal=True))
    assert not four_app_gate(1, dict(settings=True, files=True, browser=True, terminal=True))
    print("tile_identity_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
