"""Extract a user-supplied case record from PDF bytes without ingesting it as law."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader


MINIMUM_TEXT_CHARACTERS = 20

CLASSIFICATION = (
    "User-supplied factual/procedural record; not a Law Wiki legal authority"
)


def _clean_page_text(value: str) -> str:
    return value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _read_pdf_pages(data: bytes, filename: str) -> list[str]:
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Cannot open case-record PDF {filename}: {exc}") from exc
    if bool(getattr(reader, "is_encrypted", False)):
        raise ValueError(
            "Encrypted case-record PDFs are not supported; provide an unlocked copy"
        )
    pages = list(getattr(reader, "pages", []))
    if not pages:
        raise ValueError("Case-record PDF contains no pages")
    extracted: list[str] = []
    for page_number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ValueError(
                f"Cannot extract text from case-record PDF page {page_number}: {exc}"
            ) from exc
        extracted.append(_clean_page_text(text))
    if sum(len(text) for text in extracted) < MINIMUM_TEXT_CHARACTERS:
        raise ValueError(
            "Case-record PDF has no usable text. It may be image-only or scanned; "
            "OCR is required before /law-wiki can use it"
        )
    return extracted


def _render_extracted_text(pages: list[str]) -> str:
    blocks = [
        f"--- Página {page_number} ---\n{text}"
        for page_number, text in enumerate(pages, start=1)
        if text
    ]
    return "\n\n".join(blocks).rstrip() + "\n"


def extract_pdf_bytes(data: bytes, filename: str) -> dict[str, Any]:
    """Extract embedded text from a case-record PDF.

    Returns ``{"text": str, "manifest": dict}``. Page breaks in ``text`` use
    ``--- Página N ---``. Encrypted, empty, and image-only PDFs raise
    ``ValueError`` with the same messages as the skill extractor.
    """
    if not isinstance(data, bytes):
        raise ValueError("Case-record PDF data must be bytes")
    if Path(filename).suffix.casefold() != ".pdf":
        raise ValueError(f"Case-record input must be a PDF: {filename}")
    pages = _read_pdf_pages(data, filename)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "case-record-input",
        "filename": Path(filename).name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "pages": len(pages),
        "pages_with_text": sum(bool(text) for text in pages),
        "empty_pages": [
            page_number
            for page_number, text in enumerate(pages, start=1)
            if not text
        ],
        "characters": sum(len(text) for text in pages),
        "extraction_method": "pypdf",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "classification": CLASSIFICATION,
    }
    return {"text": _render_extracted_text(pages), "manifest": manifest}
