#!/usr/bin/env python3
"""Heuristic secret scan with redacted, path-only findings.

The scanner checks non-ignored worktree files and every reachable Git blob.
It never prints matching text or secret values.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private-key",
        re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    ),
    ("gitlab-pat", re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    (
        "github-token",
        re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ),
    ("aws-access-key-id", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(rb"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("slack-token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-live-secret", re.compile(rb"\bsk_live_[A-Za-z0-9]{16,}\b")),
    (
        "jwt",
        re.compile(
            rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
    (
        "assigned-credential",
        re.compile(
            rb"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|"
            rb"private[_-]?token|secret)\b\s*[:=]\s*[\"']?([^\s\"'#,;]{8,})"
        ),
    ),
)

PLACEHOLDERS = {
    b"changeme",
    b"example",
    b"placeholder",
    b"redacted",
    b"replace_me",
    b"your_token",
}


def git_bytes(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args],
        check=True,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def matched_types(data: bytes) -> set[str]:
    if is_binary(data):
        return set()

    matches: set[str] = set()
    for finding_type, pattern in PATTERNS:
        for match in pattern.finditer(data):
            if finding_type == "assigned-credential":
                candidate = match.group(1).strip().lower()
                if candidate in PLACEHOLDERS or candidate.startswith((b"<", b"${", b"{{")):
                    continue
            matches.add(finding_type)
    return matches


def worktree_findings() -> set[tuple[str, str]]:
    findings: set[tuple[str, str]] = set()
    paths = git_bytes("ls-files", "-co", "--exclude-standard", "-z").split(b"\0")
    for raw_path in paths:
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        try:
            data = Path(path).read_bytes()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            continue
        for finding_type in matched_types(data):
            findings.add((finding_type, path))
    return findings


def history_findings() -> set[tuple[str, str]]:
    findings: set[tuple[str, str]] = set()
    object_paths: dict[str, str] = {}
    for line in git_bytes("rev-list", "--objects", "--all").splitlines():
        object_id, separator, raw_path = line.partition(b" ")
        if separator and raw_path:
            object_paths.setdefault(
                object_id.decode("ascii"),
                raw_path.decode("utf-8", errors="surrogateescape"),
            )

    object_ids = "".join(f"{object_id}\n" for object_id in object_paths).encode("ascii")
    metadata = git_bytes(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        input_data=object_ids,
    )
    blob_ids = {
        line.split(b" ", 1)[0].decode("ascii")
        for line in metadata.splitlines()
        if line.endswith(b" blob")
    }

    for object_id in blob_ids:
        data = git_bytes("cat-file", "blob", object_id)
        for finding_type in matched_types(data):
            findings.add((finding_type, object_paths[object_id]))
    return findings


def main() -> int:
    current = worktree_findings()
    history = history_findings()

    for scope, findings in (("worktree", current), ("history", history)):
        for finding_type, path in sorted(findings):
            print(f"FINDING type={scope}/{finding_type} path={path}")

    total = len(current) + len(history)
    print(
        "Secret scan completed: "
        f"worktree_findings={len(current)} history_findings={len(history)}."
    )
    if total:
        print("Only finding types and paths are shown; values are always redacted.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
