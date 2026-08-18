#!/usr/bin/env python3
"""Public-readiness scan for a local git/jj package tree."""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from typing import Iterable

SECRET_RES = [
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gho_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(
        r"(password|api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token)\s*[:=]\s*\S{8,}",
        re.IGNORECASE,
    ),
]
INFRA_RE = re.compile(
    r"(?:\b(?:10|127|192\.168)\.\d{1,3}\.\d{1,3}\b|"
    r"\b172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}\b|"
    r"\.lan\b|/srv/bigs-runtime|/home/[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


def run(repo, args, timeout=120):
    return subprocess.run(args, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def redact(text: str) -> str:
    text = re.sub(
        r"((?:password|api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token)\s*[:=]\s*)\S+",
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"ghp_[A-Za-z0-9_]+", "ghp_[REDACTED]", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]+", "github_pat_[REDACTED]", text)
    text = re.sub(r"gho_[A-Za-z0-9_]+", "gho_[REDACTED]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "sk-[REDACTED]", text)
    return text.strip()[:300]


def git_ls(repo, extra):
    cp = run(repo, ["git", *extra])
    if cp.returncode != 0:
        if extra[:1] == ["ls-files"]:
            return [str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
        raise SystemExit(cp.stderr.strip() or f"git {' '.join(extra)} failed")
    return [line for line in cp.stdout.splitlines() if line]


def is_secret_line(line: str) -> bool:
    return any(p.search(line) for p in SECRET_RES)


def grep_files(repo, files: Iterable[str], personal_re, max_samples):
    out = {
        "secrets": {"total": 0, "samples": []},
        "infrastructure": {"total": 0, "samples": []},
        "personal_terms": {"total": 0, "samples": []},
    }
    for rel in files:
        p = repo / rel
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            checks = {
                "secrets": is_secret_line(line),
                "infrastructure": bool(INFRA_RE.search(line)),
                "personal_terms": bool(personal_re.search(line)) if personal_re.pattern != "(?!)" else False,
            }
            for name, hit in checks.items():
                if not hit:
                    continue
                bucket = out[name]
                bucket["total"] += 1
                if len(bucket["samples"]) < max_samples:
                    bucket["samples"].append({"path": rel, "line": lineno, "text": redact(line)})
    return out


def grep_history(repo, predicate, max_samples):
    if not (repo / ".git").exists():
        return {"commits": 0, "total": 0, "samples": []}
    revs = git_ls(repo, ["rev-list", "--all"])
    if not revs:
        return {"commits": 0, "total": 0, "samples": []}
    cp = run(
        repo,
        ["git", "grep", "-nI", "-E", r"PRIVATE KEY|ghp_|gho_|github_pat_|AKIA|AIza|password|api_key|token", *revs],
        timeout=180,
    )
    lines = cp.stdout.splitlines() if cp.stdout else []
    samples = []
    total = 0
    seen = set()
    for raw in lines:
        parts = raw.split(":", 3)
        if len(parts) < 4:
            continue
        _, path, lineno, content = parts
        if not predicate(content):
            continue
        total += 1
        key = (path, lineno, content)
        if key in seen:
            continue
        seen.add(key)
        if len(samples) < max_samples:
            samples.append({"path": path, "line": lineno, "text": redact(content)})
    return {"commits": len(revs), "total": total, "samples": samples}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--terms", default="")
    ap.add_argument("--max-samples", type=int, default=25)
    args = ap.parse_args()
    repo = pathlib.Path(args.repo).expanduser().resolve()
    term_parts = [re.escape(t.strip()) for t in args.terms.split(",") if t.strip()]
    personal_re = re.compile("|".join(term_parts), re.IGNORECASE) if term_parts else re.compile(r"(?!)")
    if (repo / ".git").exists():
        tracked = git_ls(repo, ["ls-files"])
        ignored = git_ls(repo, ["status", "--short", "--ignored"])
        remote = run(repo, ["git", "remote", "get-url", "origin"])
    else:
        tracked = [str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
        ignored = []
        remote = None
    report = {
        "repo": str(repo),
        "tracked_files": len(tracked),
        "tracked_scan": grep_files(repo, tracked, personal_re, args.max_samples),
        "history_scan": {
            "secrets": grep_history(repo, is_secret_line, args.max_samples),
            "personal_or_infra_terms": grep_history(
                repo,
                lambda line: bool(personal_re.search(line) or INFRA_RE.search(line)),
                args.max_samples,
            ),
        },
        "ignored_or_untracked": ignored[:200],
        "remote": {"origin": remote.stdout.strip()} if remote and remote.returncode == 0 else None,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
