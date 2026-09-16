#!/usr/bin/env python3
"""Fail before GitHub publication when source or artifact limits are unsafe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GITHUB_FILE_LIMIT = 100 * 1024 * 1024
DEFAULT_ARTIFACT_LIMIT = 950 * 1024 * 1024


def inspect(root: Path, artifact_limit: int = DEFAULT_ARTIFACT_LIMIT) -> dict[str, object]:
    oversized: list[str] = []
    artifact_size = 0
    ignored_parts = {".git", "node_modules", ".astro"}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue
        size = path.stat().st_size
        if size >= GITHUB_FILE_LIMIT:
            oversized.append(f"{path.relative_to(root).as_posix()} ({size} bytes)")
        if "site" in path.parts and "dist" in path.parts:
            artifact_size += size
    return {
        "ok": not oversized and artifact_size <= artifact_limit,
        "oversized_files": oversized,
        "artifact_bytes": artifact_size,
        "artifact_limit_bytes": artifact_limit,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact-limit", type=int, default=DEFAULT_ARTIFACT_LIMIT)
    args = parser.parse_args()
    report = inspect(args.root.resolve(), args.artifact_limit)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
