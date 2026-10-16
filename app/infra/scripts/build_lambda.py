#!/usr/bin/env python3
"""Build the Lambda asset directory without Docker.

Wipes <repo>/build/lambda, pip-installs app/requirements.txt for the
Linux x86_64 / CPython 3.12 Lambda runtime, then copies the app package.
boto3 is not packaged; the Lambda runtime provides it.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build" / "lambda"
REQ = ROOT / "app" / "requirements.txt"
APP = ROOT / "app"

# Top-level app directories that must not ship in the Lambda zip.
SKIP_TOP = {"web", "infra", "tests", "eval"}
SKIP_ANYWHERE = {"__pycache__", "node_modules"}
BOTO_PACKAGES = ("boto3", "botocore", "s3transfer")


def _chmod_and_retry(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _wipe(path: Path) -> None:
    if not path.exists():
        return
    shutil.rmtree(path, onexc=_chmod_and_retry)


def _ignore(directory: str, names: list[str]) -> set[str]:
    at_app_root = Path(directory).resolve() == APP.resolve()
    skipped: set[str] = set()
    for name in names:
        if name in SKIP_ANYWHERE or name.endswith(".pyc"):
            skipped.add(name)
        elif at_app_root and name in SKIP_TOP:
            skipped.add(name)
    return skipped


def _strip_boto(build: Path) -> None:
    for name in BOTO_PACKAGES:
        package_dir = build / name
        if package_dir.exists():
            shutil.rmtree(package_dir, onexc=_chmod_and_retry)
        for dist in build.glob(f"{name}-*.dist-info"):
            shutil.rmtree(dist, onexc=_chmod_and_retry)


def _total_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> None:
    if not REQ.is_file():
        raise SystemExit(f"requirements file not found: {REQ}")
    if not APP.is_dir():
        raise SystemExit(f"app package not found: {APP}")

    _wipe(BUILD)
    BUILD.mkdir(parents=True)

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(REQ),
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--target",
            str(BUILD),
        ]
    )

    _strip_boto(BUILD)
    for name in BOTO_PACKAGES:
        if (BUILD / name).exists():
            raise SystemExit(f"{name} must not be packaged; the Lambda runtime provides boto3")

    shutil.copytree(APP, BUILD / "app", ignore=_ignore)
    for banned in SKIP_TOP:
        if (BUILD / "app" / banned).exists():
            raise SystemExit(f"lambda build incorrectly contains app/{banned}")

    total = _total_bytes(BUILD)
    print(f"build/lambda: {total} bytes ({total / (1024 * 1024):.2f} MiB)")


if __name__ == "__main__":
    main()
