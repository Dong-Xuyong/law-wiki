#!/usr/bin/env python3
"""Ingest immutable PDFs placed under raw/pdfs/<website>/<year>/."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

import import_csv


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised by CLI environments
        raise SystemExit("Install PDF support with: python -m pip install -r requirements.txt") from exc
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def pdf_record(root: Path, path: Path, text: str) -> dict[str, Any]:
    relative = path.relative_to(root / "raw" / "pdfs")
    if len(relative.parts) < 3:
        raise ValueError(f"PDF path must be raw/pdfs/<website>/<year>/<filename>: {relative}")
    website, year = relative.parts[0], relative.parts[1]
    nested = "/".join(relative.parts[2:-1])
    folder = "/".join(part for part in ("PDFs", website, year, nested) if part)
    filename = relative.name
    document_id = import_csv.document_id(website, folder, filename)
    file_slug = import_csv.slugify(path.stem, "document")
    website_slug = import_csv.slugify(website, "website")
    return {
        "id": document_id,
        "folder": folder,
        "filename": filename,
        "title": path.stem,
        "year": year,
        "website": website,
        "website_slug": website_slug,
        "topic": "PDF importado",
        "topic_raw": "PDF importado",
        "topic_kind": "collection",
        "topic_slug": "pdf-importado",
        "sector": "",
        "sectors": [],
        "categories": ["supplied-material"],
        "document_type": "unknown",
        "content_hash": import_csv.content_hash(text),
        "text_chars": len(text),
        "summary_chars": 0,
        "tokens": 0,
        "tokens_sm": 0,
        "is_empty": str(not bool(text)),
        "short_text": len(text) <= import_csv.SHORT_TEXT_CHARS,
        "rel_raw": f"raw/documents/{website_slug}/{year}/{document_id}.md",
        "rel_source": f"wiki/sources/{file_slug}--{document_id}.md",
        "source_slug": f"{file_slug}--{document_id}",
        "pdf_path": path.relative_to(root).as_posix(),
        "source_format": "pdf",
        "verification": "unverified",
    }


def raw_markdown(record: dict[str, Any], text: str, imported: str) -> str:
    frontmatter = import_csv.render_frontmatter([
        ("id", record["id"]), ("folder", record["folder"]), ("filename", record["filename"]),
        ("year", record["year"]), ("website", record["website"]), ("topic", record["topic_raw"]),
        ("source_format", "pdf"), ("pdf", record["pdf_path"]),
        ("content_hash", record["content_hash"]), ("imported", imported),
    ])
    return f"{frontmatter}\n\n# {record['title']}\n\n## Full text\n\n{text}\n"


def source_markdown(record: dict[str, Any], imported: str) -> str:
    frontmatter = import_csv.render_frontmatter([
        ("tags", ["sources", "pdf-importado", record["website_slug"]]),
        ("id", record["id"]), ("title", record["title"]),
        ("aliases", [record["id"], record["filename"]]), ("folder", record["folder"]),
        ("filename", record["filename"]), ("year", record["year"]), ("website", record["website"]),
        ("topic", record["topic_raw"]), ("topic_raw", record["topic_raw"]),
        ("raw", record["rel_raw"]), ("pdf", record["pdf_path"]),
        ("content_hash", record["content_hash"]),
        ("document_type", "unknown"), ("jurisdiction", "unknown"),
        ("authority_level", "unknown"), ("citation", record["filename"]),
        ("legal_status", "unknown"), ("as_of", record["year"] or "unknown"),
        ("verification", "unverified"), ("enriched", False),
        ("enrichment_state", "imported-unverified"), ("source_format", "pdf"),
        ("generated_kind", "pdf-source"),
        ("generated_fingerprint", import_csv.FINGERPRINT_TOKEN),
        ("created", imported), ("updated", imported),
    ])
    content = (
        f"{frontmatter}\n\n# {record['title']}\n\n## Status\n\n"
        "PDF importado, ainda não verificado. Auxiliar de pesquisa; não constitui aconselhamento jurídico.\n\n"
        "## Summary\n\nSem resumo verificado.\n\n"
        "## Source metadata\n\n"
        f"- Organization: {record['website']}\n- Folder: `{record['folder']}`\n"
        f"- Filename: `{record['filename']}`\n- Year: {record['year']}\n"
        f"- Document id: `{record['id']}`\n\n"
        "## Key holdings / issues\n\nUnknown until verified against the raw text.\n\n"
        "## Entities mentioned\n\n- None extracted.\n\n"
        "## Concepts\n\n- None extracted.\n\n"
        "## Pinpoint quotations\n\n- None extracted.\n\n"
        "## Related sources\n\n- None established.\n\n"
        "## Raw source\n\n"
        f"- [[{record['rel_raw'].removesuffix('.md')}]] — extracted immutable text\n"
        f"- `{record['pdf_path']}` — immutable original PDF\n"
    )
    return import_csv.add_fingerprint(content)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
        newline="\n",
    )


def import_pdfs(
    root: Path,
    extractor: Callable[[Path], str] = extract_pdf_text,
) -> dict[str, Any]:
    root = root.resolve()
    imported = import_csv.today_iso()
    pdf_root = root / "raw" / "pdfs"
    catalog_path = root / "data" / "pdf-catalog.jsonl"
    existing_rows = {
        str(row["id"]): row
        for row in (
            json.loads(line)
            for line in catalog_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    } if catalog_path.exists() else {}
    stats: dict[str, Any] = {"pdfs": 0, "written": 0, "unchanged": 0, "protected": []}
    if not pdf_root.exists():
        write_jsonl(catalog_path, [])
        return stats

    for path in sorted(pdf_root.rglob("*.pdf"), key=lambda item: item.as_posix().casefold()):
        stats["pdfs"] += 1
        text = extractor(path).replace("\r\n", "\n").replace("\r", "\n")
        record = pdf_record(root, path, text)
        raw_path = root / record["rel_raw"]
        source_path = root / record["rel_source"]
        existing = existing_rows.get(record["id"])
        if existing and existing.get("content_hash") != record["content_hash"]:
            stats["protected"].append(f"{record['id']}: PDF extraction changed")
            continue
        if raw_path.exists():
            fields = import_csv.parse_frontmatter(raw_path.read_text(encoding="utf-8"))
            if fields.get("content_hash") != record["content_hash"]:
                stats["protected"].append(f"{record['id']}: raw text changed")
                continue
        else:
            import_csv.write_text(raw_path, raw_markdown(record, text, imported))

        desired_source = source_markdown(record, imported)
        if source_path.exists() and source_path.read_text(encoding="utf-8") != desired_source:
            if not import_csv.fingerprint_valid(source_path.read_text(encoding="utf-8")):
                stats["protected"].append(f"{record['id']}: protected source page")
                continue
        import_csv.write_text(source_path, desired_source)
        existing_rows[record["id"]] = record
        stats["written"] += 1

    write_jsonl(catalog_path, sorted(existing_rows.values(), key=lambda row: str(row["id"])))
    stats["unchanged"] = stats["pdfs"] - stats["written"] - len(stats["protected"])
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    stats = import_pdfs(args.root)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 1 if stats["protected"] else 0


if __name__ == "__main__":
    sys.exit(main())
