#!/usr/bin/env python3
"""Verify import parity plus connection-graph invariants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lint_wiki


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected", type=int)
    args = parser.parse_args()
    report = lint_wiki.lint(args.root, args.expected)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
