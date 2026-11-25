#!/usr/bin/env python3
"""Fail when Git tracks runtime, user, or generated files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath


FORBIDDEN_DIRECTORIES = {"__pycache__", "attachments", "build", "data", "dist"}
SQLITE_PATH = re.compile(r"\.(?:db|sqlite|sqlite3)(?:$|[-.])", re.IGNORECASE)


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def violation_reason(path: str) -> str | None:
    normalized = PurePosixPath(path)
    lower_path = path.lower()
    lower_name = normalized.name.lower()

    forbidden_component = next(
        (part for part in normalized.parts if part.lower() in FORBIDDEN_DIRECTORIES),
        None,
    )
    if forbidden_component:
        return f"forbidden directory: {forbidden_component}"

    if (
        len(normalized.parts) == 2
        and normalized.parts[0].lower() == "context"
        and normalized.suffix.lower() == ".json"
    ):
        return "raw context JSON"

    if lower_name.endswith((".pyc", ".pyo", ".pyd")):
        return "Python bytecode"

    if SQLITE_PATH.search(lower_path):
        return "SQLite runtime/backup"

    return None


def main() -> int:
    violations = [
        (path, reason)
        for path in tracked_paths()
        if (reason := violation_reason(path)) is not None
    ]
    if violations:
        print("Git hygiene check failed; forbidden tracked paths:", file=sys.stderr)
        for path, reason in violations:
            print(f"- {reason}: {path}", file=sys.stderr)
        return 1

    print("Git hygiene check passed: no forbidden paths are tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
