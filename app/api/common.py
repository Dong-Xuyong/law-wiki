"""Shared constants and small helpers for the Minutas API.

No engine imports. Case text must never be logged by callers.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# Exact sentence required on every exported decision (CONTRACTS.md).
CSM_SENTENCE = (
    "Decisão produzida com o auxílio de sistema de IA, de acordo com as "
    "recomendações do CSM. Integralmente revisto pelo signatário."
)

REQUIRED_SECTIONS = (
    "sumario",
    "relatorio",
    "objeto_litigio",
    "saneador",
    "factos_provados",
    "factos_nao_provados",
    "motivacao",
    "fundamentacao_direito",
    "decisao",
)

SECTION_ORDER = {name: index for index, name in enumerate(REQUIRED_SECTIONS)}

MAX_TITLE_CHARS = 200
MAX_RECORD_CHARS = 200_000
MAX_PARAGRAPH_CHARS = 20_000
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_SEARCH_K = 20
DEFAULT_SEARCH_K = 8
MAX_SOURCE_LINES = 200
PRESIGN_SECONDS = 600
MAX_ERROR_CHARS = 1000

PUBLIC_DOCUMENT_URL = "https://dong-xuyong.github.io/law-wiki/documents/{document_id}/"

REVIEWED_STATUSES = frozenset({"accepted", "edited", "rejected"})
REVIEW_STATUS_FOR_ACTION = {
    "accept": "accepted",
    "edit": "edited",
    "reject": "rejected",
}


class ApiError(Exception):
    """Expected HTTP failure. `extra` is merged into the JSON body."""

    def __init__(self, status: int, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


class WorkerError(Exception):
    """Controlled worker failure whose message is safe to persist."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def now_iso() -> str:
    """UTC timestamp with microseconds, suffixed with Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def new_public_id(prefix: str) -> str:
    """`prefix` plus 10 chars from `[a-z0-9]` (`c_` or `d_`)."""
    suffix = "".join(secrets.choice(ID_ALPHABET) for _ in range(10))
    return prefix + suffix


def new_rand4() -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(4))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def paragraph_sort_key(item: dict) -> tuple:
    section = str(item.get("section") or "")
    try:
        index = int(item.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    return (SECTION_ORDER.get(section, len(REQUIRED_SECTIONS)), index, str(item.get("id") or ""))


def template_path() -> Path:
    configured = os.environ.get("LW_TEMPLATE_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "engine" / "templates" / "decisao-arbitral-wiki.docx"


def tmp_dir() -> Path:
    """DOCX scratch directory.

    Lambda is Linux and uses `/tmp`. Windows tests use the system temp
    directory so the process does not need a drive-root `/tmp`.
    """
    override = os.environ.get("LW_TMP_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        path = Path(tempfile.gettempdir()) / "minutas"
    else:
        path = Path("/tmp")
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_docx_path(draft_id: str) -> Path:
    return tmp_dir() / f"{draft_id}.docx"


def concise(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    if len(line) > limit:
        return line[:limit]
    return line


def sync_draft_summary(store: object, meta: dict) -> None:
    """Mirror meta status onto the case's draft summary item."""
    summary = store.get_item(f"CASE#{meta['caseId']}", f"DRAFT#{meta['draftId']}")  # type: ignore[attr-defined]
    if summary is None:
        return
    summary["status"] = meta.get("status", summary.get("status"))
    store.put_item(summary)  # type: ignore[attr-defined]


def write_audit(store: object, draft_id: str, actor: str, action: str, **fields: object) -> dict:
    stamp = now_iso()
    item: dict = {
        "PK": f"AUDIT#{draft_id}",
        "SK": f"{stamp}#{new_rand4()}",
        "draftId": draft_id,
        "actor": actor,
        "action": action,
        "at": stamp,
    }
    for key, value in fields.items():
        if value is not None:
            item[key] = value
    store.put_item(item)  # type: ignore[attr-defined]
    return item
