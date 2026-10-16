"""Locate the FTS index locally, or download it once per Lambda container."""

from __future__ import annotations

import os
import threading
from pathlib import Path

# Overridden in tests. Lambda's writable disk is /tmp (ephemeral, up to the
# function's configured size). A warm container keeps this file: a new object
# in S3 is picked up on the next cold start.
CACHE_PATH = Path("/tmp/fts.sqlite3")
LOCAL_INDEX = Path("build/index/fts.sqlite3")
DEFAULT_S3_KEY = "index/fts.sqlite3"

_download_lock = threading.Lock()


def ensure_local_index() -> Path:
    """Return the SQLite file the retriever should open.

    When ``LW_CORPUS_BUCKET`` is set, download
    ``s3://$LW_CORPUS_BUCKET/$LW_INDEX_S3_KEY`` (default key
    ``index/fts.sqlite3``) to ``/tmp/fts.sqlite3`` if that file is absent.
    Otherwise return ``LW_INDEX_PATH`` when set, or ``build/index/fts.sqlite3``.
    """

    bucket = os.environ.get("LW_CORPUS_BUCKET", "").strip()
    if bucket:
        return _ensure_s3_cache(bucket)
    override = os.environ.get("LW_INDEX_PATH", "").strip()
    if override:
        return Path(override)
    return LOCAL_INDEX


def _ensure_s3_cache(bucket: str) -> Path:
    dest = CACHE_PATH
    if dest.is_file():
        return dest
    with _download_lock:
        if dest.is_file():
            return dest
        key = os.environ.get("LW_INDEX_S3_KEY", "").strip() or DEFAULT_S3_KEY
        _download_index(bucket, key, dest)
    return dest


def _download_index(bucket: str, key: str, dest: Path) -> None:
    # boto3 ships in the Lambda runtime and is not a local retrieval dependency.
    import boto3

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    region = os.environ.get("LW_REGION", "").strip() or os.environ.get(
        "AWS_REGION", ""
    ).strip()
    client = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    try:
        client.download_file(bucket, key, str(partial))
        os.replace(partial, dest)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
