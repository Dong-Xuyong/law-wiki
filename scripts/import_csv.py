#!/usr/bin/env python3
"""Import df_organized.csv into an Obsidian law wiki (standard library only)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

EXPECTED_COLUMNS = [
    "folder", "filename", "text", "is_empty", "year", "website",
    "Topic", "tokens", "summary", "tokens_sm",
]
ID_PREFIX = "lawwiki:v1"
EXTRACTOR_VERSION = "lawwiki-importer:2"
SHORT_TEXT_CHARS = 500
CSV_FIELD_LIMIT = 1_000_000
PAGE_SIZE = 200
FINGERPRINT_TOKEN = "__GENERATED_FINGERPRINT__"
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
FINGERPRINT_RE = re.compile(r"(?m)^generated_fingerprint:\s*(?:\"[^\"]*\"|'[^']*'|\S*)\s*$")
GENERATED_DATE_RE = re.compile(r"(?m)^(?:created|updated):\s*.*$")


def configure_csv() -> None:
    csv.field_size_limit(CSV_FIELD_LIMIT)


def today_iso() -> str:
    return date.today().isoformat()


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_list(values: Iterable[str]) -> str:
    return "[" + ", ".join(yaml_scalar(v) for v in values if v) + "]"


def normalize_key(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "").strip().replace("\\", "/")
    return re.sub(r"/+", "/", text).casefold()


def slugify(value: str, fallback: str = "item") -> str:
    text = unicodedata.normalize("NFC", value or "").strip().replace("\\", "-").replace("/", "-").casefold()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")[:80] or fallback


def document_id(website: str, folder: str, filename: str) -> str:
    payload = "\0".join(
        [ID_PREFIX, normalize_key(website), normalize_key(folder), normalize_key(filename)]
    ).encode("utf-8")
    return "law_" + hashlib.sha256(payload).hexdigest()[:16]


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, raw = line.split(":", 1)
        fields[key.strip()] = raw.strip().strip('"').strip("'")
    return fields


def int_or_zero(value: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def truthy_flag(value: str) -> bool:
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    configure_csv()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        got = [name.strip() for name in (reader.fieldnames or [])]
        if got != EXPECTED_COLUMNS:
            raise SystemExit(f"Unexpected CSV columns.\nExpected: {EXPECTED_COLUMNS}\nGot: {got}")
        rows = []
        for index, row in enumerate(reader, start=1):
            record = {key: (row.get(key) or "") for key in EXPECTED_COLUMNS}
            record["_csv_row"] = str(index)
            rows.append(record)
        return rows


def load_topic_map(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "data" / "topic-map.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    topics = payload.get("topics", {})
    if not isinstance(topics, dict):
        raise SystemExit("data/topic-map.json: 'topics' must be an object")
    return topics


def document_type_for(topic: str, mapping: dict[str, Any]) -> str:
    categories = mapping.get("categories") or []
    if "legislation" in categories:
        return "legislation"
    if "arbitral-decisions" in categories:
        return "arbitral-decision"
    return "unknown"


def enrich_record(row: dict[str, str], topic_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    website, folder, filename = (row[k].strip() for k in ("website", "folder", "filename"))
    topic_raw, year = row["Topic"].strip(), row["year"].strip()
    mapping = (topic_map or {}).get(topic_raw, {})
    doc_id = document_id(website, folder, filename)
    website_slug, topic_slug = slugify(website, "website"), slugify(topic_raw, "topic")
    file_slug = slugify(Path(filename).stem, "document")
    sector = mapping.get("sector") if isinstance(mapping.get("sector"), str) else ""
    categories = [str(v) for v in mapping.get("categories", []) if isinstance(v, str)]
    return {
        "csv_row": int(row["_csv_row"]), "id": doc_id, "folder": folder,
        "filename": filename, "text": row["text"], "summary": row["summary"],
        "summary_hash": content_hash(row["summary"]), "is_empty": row["is_empty"].strip(),
        "year": year, "website": website, "topic": topic_raw, "topic_raw": topic_raw,
        "topic_kind": str(mapping.get("kind") or "unmapped"), "sector": sector,
        "sectors": [sector] if sector else [], "categories": categories,
        "tokens": int_or_zero(row["tokens"]), "tokens_sm": int_or_zero(row["tokens_sm"]),
        "content_hash": content_hash(row["text"]), "website_slug": website_slug,
        "topic_slug": topic_slug, "folder_slug": slugify(folder, "folder"),
        "source_slug": f"{file_slug}--{doc_id}", "title": Path(filename).stem.strip() or filename,
        "rel_raw": f"raw/documents/{website_slug}/{year or 'unknown'}/{doc_id}.md",
        "rel_source": f"wiki/sources/{file_slug}--{doc_id}.md",
        "short_text": len(row["text"]) <= SHORT_TEXT_CHARS,
        "document_type": document_type_for(topic_raw, mapping),
    }


def render_frontmatter(fields: list[tuple[str, Any]]) -> str:
    lines = ["---"]
    for key, value in fields:
        lines.append(f"{key}: {yaml_list(value) if isinstance(value, list) else yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def add_fingerprint(content: str) -> str:
    digest = content_hash(content)
    return content.replace(FINGERPRINT_TOKEN, digest, 1)


def fingerprint_valid(content: str) -> bool:
    fields = parse_frontmatter(content)
    stored = fields.get("generated_fingerprint", "")
    if not stored:
        return False
    normalized, count = FINGERPRINT_RE.subn(
        f"generated_fingerprint: {yaml_scalar(FINGERPRINT_TOKEN)}", content, count=1
    )
    return count == 1 and content_hash(normalized) == stored


def generated_semantics(content: str) -> str:
    """Return generated content with run-date and fingerprint noise removed."""
    content = FINGERPRINT_RE.sub("generated_fingerprint: __ignored__", content, count=1)
    return GENERATED_DATE_RE.sub(lambda match: match.group(0).split(":", 1)[0] + ": __ignored__", content)


def generated_write(
    path: Path,
    content: str,
    reports: list[str],
    stats: dict[str, Any],
    kind: str,
    legacy_v1: Iterable[str] = (),
) -> str:
    generated = add_fingerprint(content)
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if old == generated or (
            fingerprint_valid(old) and generated_semantics(old) == generated_semantics(generated)
        ):
            stats["generated_unchanged"] += 1
            return "unchanged"
        valid_fingerprint = fingerprint_valid(old)
        exact_legacy = any(old == candidate for candidate in legacy_v1)
        if not valid_fingerprint and not exact_legacy:
            stats["protected_conflicts"] += 1
            reports.append(f"{kind}: {path.as_posix()}")
            return "protected"
        if exact_legacy:
            stats["legacy_v1_migrated"] += 1
    write_text(path, generated)
    stats["generated_written"] += 1
    return "written"


def raw_markdown(record: dict[str, Any], imported: str) -> str:
    fm = render_frontmatter([
        ("id", record["id"]), ("folder", record["folder"]), ("filename", record["filename"]),
        ("year", record["year"]), ("website", record["website"]), ("topic", record["topic_raw"]),
        ("tokens", record["tokens"]), ("tokens_sm", record["tokens_sm"]),
        ("is_empty", record["is_empty"]), ("content_hash", record["content_hash"]),
        ("csv_row", record["csv_row"]), ("imported", imported),
    ])
    body = record["text"].replace("\r\n", "\n").replace("\r", "\n")
    return f"{fm}\n\n# {record['title']}\n\n## Full text\n\n{body}\n"


def legacy_created(path: Path, fallback: str) -> str:
    """Read the v1 creation date without trusting it as proof of generation."""
    if not path.exists():
        return fallback
    value = parse_frontmatter(path.read_text(encoding="utf-8")).get("created", "")
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else fallback


def legacy_v1_source_markdown(record: dict[str, Any], imported: str) -> str:
    """Reconstruct the exact source output emitted by importer v1."""
    fm = render_frontmatter([
        ("tags", ["sources", record["topic_slug"], record["website_slug"]]),
        ("id", record["id"]), ("title", record["title"]),
        ("aliases", [record["id"], record["filename"]]), ("folder", record["folder"]),
        ("filename", record["filename"]), ("year", record["year"]), ("website", record["website"]),
        ("topic", record["topic_raw"]), ("tokens", record["tokens"]), ("tokens_sm", record["tokens_sm"]),
        ("is_empty", record["is_empty"]), ("content_hash", record["content_hash"]),
        ("csv_row", record["csv_row"]), ("raw", record["rel_raw"]),
        ("jurisdiction", "Portugal"), ("jurisdiction_source", "corpus-default"),
        ("authority_level", "unknown"), ("citation", record["filename"]),
        ("legal_status", "unknown"), ("as_of", record["year"] or "unknown"),
        ("verification", "unverified"), ("enriched", False),
        ("created", imported), ("updated", imported),
    ])
    summary = record["summary"].replace("\r\n", "\n").replace("\r", "\n").strip()
    flags = []
    if record["short_text"]:
        flags.append(
            f"Short full text ({len(record['text'])} characters) — review against the raw file."
        )
    if truthy_flag(record["is_empty"]) and record["text"].strip():
        flags.append(
            "`is_empty` is true in the CSV but the full text is not empty — "
            "ignore `is_empty` as a filter."
        )
    flag_block = ""
    if flags:
        flag_block = "## Import flags\n\n" + "\n".join(f"- {item}" for item in flags) + "\n\n"
    return (
        f"{fm}\n\n# {record['title']}\n\n## Status\n\n"
        "Imported digest from the CSV `summary` column. "
        "**Unverified** against the full text. This page is a research aid, not legal advice. "
        "Do not treat the summary as a holding, ratio, or current statement of law until it is checked against "
        f"[[{record['rel_raw'].removesuffix('.md')}|the raw document]].\n\n"
        f"{flag_block}## Summary\n\n{summary}\n\n## Source metadata\n\n"
        f"- Organization: [[entities/{record['website_slug']}|{record['website']}]]\n"
        f"- Topic: [[concepts/{record['topic_slug']}|{record['topic_raw']}]]\n"
        f"- Folder: `{record['folder']}`\n- Filename: `{record['filename']}`\n"
        f"- Year: {record['year']}\n- CSV row: {record['csv_row']}\n"
        f"- Tokens (full text / summary): {record['tokens']} / {record['tokens_sm']}\n"
        f"- Document id: `{record['id']}`\n\n## Raw source\n\n"
        f"- [[{record['rel_raw'].removesuffix('.md')}]] — immutable full text\n"
    )


def legacy_v1_entity_markdown(
    website: str, slug: str, records: list[dict[str, Any]], imported: str
) -> str:
    years = sorted({record["year"] for record in records if record["year"]})
    fm = render_frontmatter([
        ("tags", ["entities", "organization", slug]), ("type", "organization"),
        ("aliases", [website]), ("sources", len(records)), ("created", imported),
        ("updated", imported), ("verification", "unverified"),
    ])
    year_line = ", ".join(years) if years else "unknown"
    return (
        f"{fm}\n\n# {website}\n\n## Overview\n\n"
        f"Source organization in this corpus (`{website}`). "
        "This page was seeded from CSV metadata. It is **not** a legal conclusion about the body's powers, "
        "jurisdiction, or current status.\n\n## Corpus count\n\n"
        f"- Documents: {len(records)}\n- Years present: {year_line}\n"
        f"- Catalog: [[indexes/by-website/{slug}]]\n\n## Appearances\n\n"
        "See the website index for every source page. Do not infer holdings from filenames or summaries alone.\n"
    )


def legacy_v1_concept_markdown(
    topic: str, slug: str, records: list[dict[str, Any]], imported: str
) -> str:
    fm = render_frontmatter([
        ("tags", ["concepts", "topic", slug]), ("aliases", [topic]),
        ("sources", len(records)), ("created", imported), ("updated", imported),
        ("verification", "unverified"),
    ])
    return (
        f"{fm}\n\n# {topic}\n\n## Definition\n\n"
        f"Topic label from the CSV `Topic` column: `{topic}`. "
        "This is a filing category, not a doctrinal definition. "
        "Do not treat the label as a statement of Portuguese (or any other) law.\n\n"
        "## Evolution\n\nNot yet synthesized. Incremental ingest should update this section from verified source pages, "
        "with pinpoint citations to raw documents.\n\n## Sources\n\n"
        f"- {len(records)} imported documents — see [[indexes/by-topic/{slug}]]\n\n"
        "## Related concepts\n\n"
        "- None established yet. Add wikilinks only after a source page supports the connection.\n"
    )


def legacy_v1_index_shard(title: str, key: str, records: list[dict[str, Any]]) -> str:
    lines = [
        f"# {title}: {key}", "",
        f"{len(records)} source pages. Generated on import. One line per document.", "",
    ]
    for record in sorted(records, key=lambda value: (value["year"], value["title"], value["id"])):
        lines.append(
            f"- [[sources/{record['source_slug']}]] — {record['title']} "
            f"({record['year']}, {record['website']}, {record['topic_raw']})"
        )
    return "\n".join(lines + [""])


def legacy_v1_master_index(
    records: list[dict[str, Any]],
    websites: dict[str, list[dict[str, Any]]],
    topics: dict[str, list[dict[str, Any]]],
) -> str:
    lines = [
        "# Wiki Index", "",
        "Catalog of this law wiki. The master file stays short; full listings live in sharded indexes. "
        "Updated on every CSV import.", "", "## Browse", "",
        "- Topics — `wiki/indexes/by-topic/`",
        "- Organizations — `wiki/indexes/by-website/`",
        "- Years — `wiki/indexes/by-year/`",
        "- Source folders — `wiki/indexes/by-folder/`", "", "## Corpus", "",
        f"- Sources: {len(records)}", f"- Organizations (entities): {len(websites)}",
        f"- Topics (concepts): {len(topics)}", "", "## Organizations", "",
    ]
    for website, group in sorted(websites.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        slug = group[0]["website_slug"]
        lines.append(
            f"- [[entities/{slug}]] — {website} ({len(group)} documents); "
            f"[[indexes/by-website/{slug}]]"
        )
    lines.extend(["", "## Topics", ""])
    for topic, group in sorted(topics.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        slug = group[0]["topic_slug"]
        lines.append(
            f"- [[concepts/{slug}]] — {topic} ({len(group)} documents); "
            f"[[indexes/by-topic/{slug}]]"
        )
    return "\n".join(lines + [""])


def legacy_v1_overview(
    records: list[dict[str, Any]],
    websites: dict[str, list[dict[str, Any]]],
    topics: dict[str, list[dict[str, Any]]],
    duplicate_groups: int,
    short_count: int,
    imported: str,
    csv_meta: dict[str, Any],
) -> str:
    year_counts = Counter(record["year"] or "unknown" for record in records)
    lines = [
        "# Overview", "",
        "Corpus snapshot for this law wiki. Statistics below are generated from the CSV import. "
        "This page does not state legal conclusions.", "", "## Corpus status", "",
        "| Metric | Value |", "| ------ | ----- |",
        f"| Sources ingested | {len(records)} |",
        f"| Organizations tracked | {len(websites)} |",
        f"| Topics tracked | {len(topics)} |",
        f"| Duplicate full-text pairs kept separate | {duplicate_groups} |",
        f"| Short texts (≤{SHORT_TEXT_CHARS} chars) | {short_count} |",
        f"| Last updated | {imported} |", "", "## Import source", "",
        f"- Path: `{csv_meta['path']}`", f"- Size bytes: {csv_meta['size']}",
        f"- SHA-256: `{csv_meta['sha256']}`", "", "## Organizations", "",
    ]
    for website, group in sorted(websites.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        lines.append(f"- [[entities/{group[0]['website_slug']}|{website}]]: {len(group)}")
    lines.extend(["", "## Topics", ""])
    for topic, group in sorted(topics.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        lines.append(f"- [[concepts/{group[0]['topic_slug']}|{topic}]]: {len(group)}")
    lines.extend(["", "## Years", ""])
    for year, count in sorted(year_counts.items()):
        lines.append(f"- [[indexes/by-year/{slugify(year, year)}|{year}]]: {count}")
    lines.extend([
        "", "## How to grow this wiki", "",
        "1. Keep `raw/` immutable after import except via the importer with an explicit force flag.",
        "2. Enrich `wiki/sources/` pages against the raw text; set `enriched: true` and `verification: verified` only after that check.",
        "3. Add doctrine, court, and party pages only when a source supports them. Cite the raw document.",
        "4. Query from `wiki/index.md`, then drill into shards, source pages, and raw text.",
        "5. Run a lint pass before treating the wiki as current law — summaries are unverified on import.",
        "",
    ])
    return "\n".join(lines)


def legacy_overview_date(path: Path, fallback: str) -> str:
    if not path.exists():
        return fallback
    match = re.search(r"\| Last updated \| (\d{4}-\d{2}-\d{2}) \|", path.read_text(encoding="utf-8"))
    return match.group(1) if match else fallback


def family_id(record: dict[str, Any]) -> str:
    return "family_" + record["content_hash"][:16]


def source_markdown(record: dict[str, Any], imported: str, duplicates: list[dict[str, Any]]) -> str:
    duplicate_links = [f"sources/{r['source_slug']}" for r in duplicates if r["id"] != record["id"]]
    fid = family_id(record) if duplicate_links else ""
    fm = render_frontmatter([
        ("tags", ["sources", record["topic_slug"], record["website_slug"]]),
        ("id", record["id"]), ("title", record["title"]),
        ("aliases", [record["id"], record["filename"]]), ("folder", record["folder"]),
        ("filename", record["filename"]), ("year", record["year"]), ("website", record["website"]),
        ("topic", record["topic_raw"]), ("topic_raw", record["topic_raw"]),
        ("topic_kind", record["topic_kind"]), ("sector", record["sector"]),
        ("categories", record["categories"]), ("tokens", record["tokens"]),
        ("tokens_sm", record["tokens_sm"]), ("is_empty", record["is_empty"]),
        ("content_hash", record["content_hash"]), ("summary_hash", record["summary_hash"]),
        ("csv_row", record["csv_row"]), ("raw", record["rel_raw"]),
        ("document_type", record["document_type"]), ("process_number", "unknown"),
        ("case", "unknown"), ("forum", "unknown"), ("decision_date", "unknown"),
        ("sectors", record["sectors"]), ("doctrines", []), ("cited_instruments", []),
        ("outcome_status", "unknown"), ("duplicate_of", duplicate_links),
        ("family", f"families/{fid}" if fid else ""), ("enrichment_state", "imported-unverified"),
        ("extractor_version", EXTRACTOR_VERSION), ("jurisdiction", "Portugal"),
        ("jurisdiction_source", "corpus-default"), ("authority_level", "unknown"),
        ("citation", record["filename"]), ("legal_status", "unknown"),
        ("as_of", record["year"] or "unknown"), ("verification", "unverified"),
        ("enriched", False), ("generated_kind", "source"),
        ("generated_fingerprint", FINGERPRINT_TOKEN), ("created", imported), ("updated", imported),
    ])
    summary = record["summary"].replace("\r\n", "\n").replace("\r", "\n").strip()
    flags = []
    if record["short_text"]:
        flags.append(f"Short full text ({len(record['text'])} characters) — review against the raw file.")
    if truthy_flag(record["is_empty"]) and record["text"].strip():
        flags.append("`is_empty` is true but full text exists — do not use it as a filter.")
    flag_block = ("## Import flags\n\n" + "\n".join(f"- {v}" for v in flags) + "\n\n") if flags else ""
    return (
        f"{fm}\n\n# {record['title']}\n\n## Status\n\n"
        "Imported CSV digest. **Unverified** against the full text; research aid, not legal advice. "
        f"Check [[{record['rel_raw'].removesuffix('.md')}|the raw document]].\n\n{flag_block}"
        f"## Summary\n\n{summary}\n\n## Source metadata\n\n"
        f"- Organization: [[entities/{record['website_slug']}|{record['website']}]]\n"
        f"- Topic (raw exact label): [[concepts/{record['topic_slug']}|{record['topic_raw']}]]\n"
        f"- Sector: {record['sector'] or 'unmapped'}\n"
        f"- Categories: {', '.join(record['categories']) or 'none mapped'}\n"
        f"- Folder: `{record['folder']}`\n- Filename: `{record['filename']}`\n"
        f"- Year: {record['year'] or 'unknown'}\n- CSV row: {record['csv_row']}\n\n"
        "## Key holdings / issues\n\nUnknown until verified against the raw text.\n\n"
        "## Entities mentioned\n\n- None extracted.\n\n## Concepts\n\n"
        f"- [[concepts/{record['topic_slug']}]] — CSV filing label only\n\n"
        "## Pinpoint quotations\n\n- None extracted.\n\n## Related sources\n\n"
        + ("\n".join(f"- [[{link}]] — duplicate full text" for link in duplicate_links) if duplicate_links else "- None established.")
        + f"\n\n## Raw source\n\n- [[{record['rel_raw'].removesuffix('.md')}]] — immutable full text\n"
    )


def seeded_page(kind: str, name: str, slug: str, records: list[dict[str, Any]], imported: str) -> str:
    is_entity = kind == "entity"
    tags = ["entities", "organization", slug] if is_entity else ["concepts", "topic", slug]
    fields: list[tuple[str, Any]] = [
        ("tags", tags), ("type", "organization" if is_entity else "topic"),
        ("aliases", [name]), ("sources", len(records)), ("verification", "unverified"),
        ("generated_kind", kind), ("generated_fingerprint", FINGERPRINT_TOKEN),
        ("created", imported), ("updated", imported),
    ]
    if not is_entity:
        fields.extend([
            ("topic_raw", name), ("topic_kind", records[0]["topic_kind"]),
            ("sector", records[0]["sector"]), ("categories", records[0]["categories"]),
        ])
    catalog = f"indexes/by-website/{slug}" if is_entity else f"indexes/by-topic/{slug}"
    label = "Source organization" if is_entity else "Exact CSV `Topic` label"
    warning = (
        "No mandate, jurisdiction, doctrine, or legal conclusion is inferred from this imported metadata."
    )
    return (
        f"{render_frontmatter(fields)}\n\n# {name}\n\n## Overview\n\n"
        f"{label} represented in this corpus. {warning}\n\n## Corpus count\n\n"
        f"- Documents: {len(records)}\n- Catalog: [[{catalog}]]\n\n"
        f"## {'Appearances' if is_entity else 'Sources'}\n\n"
        "Use the catalog and verify propositions against immutable raw documents.\n"
    )


def navigation(parent: str, previous: str, following: str) -> str:
    links = [f"Parent: [[{parent}]]"]
    if previous:
        links.append(f"Previous: [[{previous}]]")
    if following:
        links.append(f"Next: [[{following}]]")
    return " · ".join(links)


def record_lines(records: list[dict[str, Any]]) -> list[str]:
    return [
        f"- [[sources/{r['source_slug']}]] — {r['title']} ({r['year'] or 'unknown'}, {r['website']}, {r['topic_raw']})"
        for r in sorted(records, key=lambda x: (x["year"], x["title"], x["id"]))
    ]


def dimension_pages(
    dimension: str, label: str, key: str, slug: str, records: list[dict[str, Any]]
) -> dict[str, str]:
    base = f"indexes/by-{dimension}/{slug}"
    links = record_lines(records)
    if len(links) <= PAGE_SIZE:
        body = [f"# {label}: {key}", "", f"{len(links)} source pages. Generated on import.", "", *links, ""]
        return {f"{base}.md": "\n".join(body)}
    pages: dict[str, str] = {}
    chunks = [links[i:i + PAGE_SIZE] for i in range(0, len(links), PAGE_SIZE)]
    child_paths = [f"{base}--page-{i:03d}" for i in range(1, len(chunks) + 1)]
    hub = [f"# {label}: {key}", "", f"{len(links)} source pages in {len(chunks)} pages.", ""]
    for i, (path, chunk) in enumerate(zip(child_paths, chunks), 1):
        hub.append(f"- [[{path}|Page {i}]] — {len(chunk)} sources")
    pages[f"{base}.md"] = "\n".join(hub + [""])
    for i, (path, chunk) in enumerate(zip(child_paths, chunks)):
        prev_path = child_paths[i - 1] if i else ""
        next_path = child_paths[i + 1] if i + 1 < len(child_paths) else ""
        pages[f"{path}.md"] = "\n".join([
            f"# {label}: {key} — page {i + 1}", "",
            navigation(base, prev_path, next_path), "", *chunk, "",
            navigation(base, prev_path, next_path), "",
        ])
    return pages


def dimension_home(dimension: str, label: str, groups: dict[str, list[dict[str, Any]]]) -> str:
    lines = [f"# {label} index", "", f"{len(groups)} {label.casefold()} values. Generated on import.", ""]
    for key, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        slug_key = group[0][f"{dimension}_slug"] if dimension in {"website", "topic", "folder"} else slugify(key, "unknown")
        lines.append(f"- [[indexes/by-{dimension}/{slug_key}|{key}]] — {len(group)}")
    return "\n".join(lines + [""])


def master_index(records: list[dict[str, Any]], dimensions: list[tuple[str, str, dict]]) -> str:
    lines = [
        "# Wiki Index", "", "Generated navigation hub. Imported summaries remain unverified.", "",
        "## Browse", "",
    ]
    for dim, label, _ in dimensions:
        lines.append(f"- [[indexes/by-{dim}/index|{label}]]")
    lines.extend(["", "## Corpus", "", f"- Sources: {len(records)}"])
    for _, label, groups in dimensions:
        lines.append(f"- {label}: {len(groups)}")
    return "\n".join(lines + [""])


def home_markdown(records: list[dict[str, Any]]) -> str:
    return "\n".join([
        "# Law Wiki Home", "",
        "Research map for the provenance-first legal knowledge graph. "
        "Imported summaries and graph assertions remain unverified legal research aids.", "",
        "## Explore", "",
        "- [[index|Wiki index]]",
        "- [[overview|Corpus overview]]",
        "- [[indexes/by-sector/index|Sectors]]",
        "- [[indexes/by-category/index|Topics and categories]]",
        "- [[indexes/by-website/index|Forums and source organizations]]",
        "- [[indexes/by-year/index|Years]]",
        "- [[indexes/by-folder/index|Source folders]]",
        "- [[cases/index|Cases]]",
        "- [[instruments/index|Legal instruments]]",
        "- [[families/index|Document families]]",
        "- [[memos/index|Research memoranda]]", "",
        "## Corpus", "",
        f"- Row-level source documents: {len(records)}",
        "- Raw documents are immutable; canonical hubs and accepted connections point back to evidence.", "",
    ])


def collection_index(title: str, description: str, links: Iterable[str] = ()) -> str:
    items = list(links)
    lines = [f"# {title}", "", description, ""]
    lines.extend(items or ["No canonical pages have been accepted yet."])
    return "\n".join(lines + [""])


def overview_markdown(records: list[dict[str, Any]], imported: str, csv_meta: dict[str, Any]) -> str:
    return "\n".join([
        "# Overview", "", "Corpus snapshot generated from CSV metadata. This page does not state legal conclusions.", "",
        "## Corpus status", "", f"- Sources ingested: {len(records)}",
        f"- Last updated: {imported}", "", "## Import source", "",
        f"- Path: `{csv_meta['path']}`", f"- Size bytes: {csv_meta['size']}",
        f"- SHA-256: `{csv_meta['sha256']}`", "",
    ])


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def append_import_log(root: Path, imported: str, csv_meta: dict[str, Any], stats: dict[str, Any]) -> None:
    path = root / "wiki" / "log.md"
    marker = f"<!-- import-sha256:{csv_meta['sha256']} -->"
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip()
    else:
        existing = "# Wiki Log\n\nAppend-only chronological record of ingests, queries, and lint passes."
    if marker in existing:
        return
    entry = "\n".join([
        f"## [{imported}] ingest df_organized.csv", "",
        marker,
        f"- Rows: {stats['rows']}",
        f"- Raw written: {stats['raw_written']}; unchanged: {stats['raw_unchanged']}; changes protected: {stats['raw_changed']}",
        f"- Sources written: {stats['sources_written']}; unchanged: {stats['sources_unchanged']}",
        f"- Protected wiki conflicts: {stats['protected_conflicts']}", "",
    ])
    write_text(path, existing + "\n\n" + entry)


def raw_change_state(path: Path, new_hash: str) -> str:
    if not path.exists():
        return "missing"
    return "unchanged" if parse_frontmatter(path.read_text(encoding="utf-8")).get("content_hash") == new_hash else "changed"


def duplicate_text_stats(records: list[dict[str, Any]]) -> tuple[int, int]:
    groups = [n for n in Counter(r["content_hash"] for r in records).values() if n > 1]
    return len(groups), sum(groups)


def clean_stale_generated(root: Path, expected: set[Path], reports: list[str], stats: dict[str, Any]) -> None:
    for directory in (root / "wiki" / "indexes", root / "wiki" / "families"):
        if not directory.exists():
            continue
        for path in directory.rglob("*.md"):
            if path in expected:
                continue
            content = path.read_text(encoding="utf-8")
            if parse_frontmatter(content).get("generated_kind") and fingerprint_valid(content):
                path.unlink()
                stats["stale_generated_deleted"] += 1
            elif "--page-" in path.name:
                reports.append(f"stale-protected: {path.as_posix()}")


def import_corpus(
    csv_path: Path, root: Path, force_raw: bool = False, limit: int | None = None
) -> dict[str, Any]:
    imported = today_iso()
    rows = read_rows(csv_path)
    if limit is not None:
        rows = rows[:limit]
    topic_map = load_topic_map(root)
    records = [enrich_record(row, topic_map) for row in rows]
    if len({r["id"] for r in records}) != len(records):
        raise SystemExit("Document id collision — extend the hash prefix.")
    csv_meta = {"path": str(csv_path), "size": csv_path.stat().st_size, "sha256": file_sha256(csv_path)}
    dimensions: dict[str, dict[str, list[dict[str, Any]]]] = {
        dim: defaultdict(list) for dim in ("website", "topic", "year", "folder", "sector", "category")
    }
    duplicates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        dimensions["website"][record["website"]].append(record)
        dimensions["topic"][record["topic_raw"]].append(record)
        dimensions["year"][record["year"] or "unknown"].append(record)
        dimensions["folder"][record["folder"] or "unknown"].append(record)
        dimensions["sector"][record["sector"] or "unmapped"].append(record)
        for category in record["categories"] or ["unmapped"]:
            dimensions["category"][category].append(record)
        duplicates[record["content_hash"]].append(record)
    stats: dict[str, Any] = {
        "rows": len(records), "raw_written": 0, "raw_unchanged": 0, "raw_changed": 0,
        "sources_written": 0, "sources_unchanged": 0, "sources_skipped_enriched": 0,
        "protected_conflicts": 0, "generated_written": 0, "generated_unchanged": 0,
        "legacy_v1_migrated": 0,
        "stale_generated_deleted": 0, "short_texts": sum(r["short_text"] for r in records),
        "concepts": len(dimensions["topic"]), "entities": len(dimensions["website"]),
    }
    stats["duplicate_groups"], stats["duplicate_rows"] = duplicate_text_stats(records)
    raw_reports: list[str] = []
    protected_reports: list[str] = []
    expected: set[Path] = set()
    for record in records:
        raw_path = root / record["rel_raw"]
        state = raw_change_state(raw_path, record["content_hash"])
        if state == "unchanged" and not force_raw:
            stats["raw_unchanged"] += 1
        elif state == "changed" and not force_raw:
            stats["raw_changed"] += 1
            raw_reports.append(f"{record['id']} {record['rel_raw']} (csv row {record['csv_row']})")
        else:
            write_text(raw_path, raw_markdown(record, imported))
            stats["raw_written"] += 1
        source_path = root / record["rel_source"]
        source_created = legacy_created(source_path, imported)
        outcome = generated_write(
            source_path, source_markdown(record, source_created, duplicates[record["content_hash"]]),
            protected_reports, stats, "source",
            [legacy_v1_source_markdown(record, source_created)],
        )
        if outcome == "written":
            stats["sources_written"] += 1
        elif outcome == "unchanged":
            stats["sources_unchanged"] += 1
        else:
            fields = parse_frontmatter(source_path.read_text(encoding="utf-8"))
            if truthy_flag(fields.get("enriched", "")):
                stats["sources_skipped_enriched"] += 1
    for website, group in dimensions["website"].items():
        path = root / "wiki" / "entities" / f"{group[0]['website_slug']}.md"
        created = legacy_created(path, imported)
        generated_write(
            path, seeded_page("entity", website, group[0]["website_slug"], group, created),
            protected_reports, stats, "entity",
            [legacy_v1_entity_markdown(website, group[0]["website_slug"], group, created)],
        )
    for topic, group in dimensions["topic"].items():
        path = root / "wiki" / "concepts" / f"{group[0]['topic_slug']}.md"
        created = legacy_created(path, imported)
        generated_write(
            path, seeded_page("concept", topic, group[0]["topic_slug"], group, created),
            protected_reports, stats, "concept",
            [legacy_v1_concept_markdown(topic, group[0]["topic_slug"], group, created)],
        )
    labels = {
        "website": "Organizations", "topic": "Topics", "year": "Years",
        "folder": "Folders", "sector": "Sectors", "category": "Categories",
    }
    dimension_spec = []
    for dim, groups in dimensions.items():
        dimension_spec.append((dim, labels[dim], groups))
        home_path = root / "wiki" / "indexes" / f"by-{dim}" / "index.md"
        content = render_frontmatter([
            ("generated_kind", "dimension-home"), ("generated_fingerprint", FINGERPRINT_TOKEN)
        ]) + "\n\n" + dimension_home(dim, labels[dim], groups)
        generated_write(home_path, content, protected_reports, stats, "dimension-home")
        expected.add(home_path)
        for key, group in groups.items():
            slug = group[0][f"{dim}_slug"] if dim in {"website", "topic", "folder"} else slugify(key, "unknown")
            for rel, body in dimension_pages(dim, labels[dim][:-1], key, slug, group).items():
                path = root / "wiki" / f"{rel}"
                generated = render_frontmatter([
                    ("generated_kind", "dimension-page"), ("generated_fingerprint", FINGERPRINT_TOKEN)
                ]) + "\n\n" + body
                old_titles = {
                    "website": "Website", "topic": "Topic",
                    "year": "Year", "folder": "Folder",
                }
                legacy = []
                if dim in old_titles and path.name == f"{slug}.md":
                    legacy.append(legacy_v1_index_shard(old_titles[dim], key, group))
                generated_write(
                    path, generated, protected_reports, stats, "dimension-page", legacy
                )
                expected.add(path)
    for digest, group in duplicates.items():
        if len(group) < 2:
            continue
        fid = "family_" + digest[:16]
        path = root / "wiki" / "families" / f"{fid}.md"
        links = "\n".join(f"- [[sources/{r['source_slug']}]] — {r['title']}" for r in group)
        family = render_frontmatter([
            ("tags", ["families", "duplicate-text"]), ("id", fid), ("content_hash", digest),
            ("verification", "unverified"), ("generated_kind", "family"),
            ("generated_fingerprint", FINGERPRINT_TOKEN), ("created", imported), ("updated", imported),
        ]) + f"\n\n# Duplicate-text family {fid}\n\nMetadata grouping only; no legal relationship is inferred.\n\n{links}\n"
        generated_write(path, family, protected_reports, stats, "family")
        expected.add(path)
    family_links = [
        f"- [[families/family_{digest[:16]}]] — {len(group)} row-level documents"
        for digest, group in sorted(duplicates.items())
        if len(group) > 1
    ]
    collection_specs = {
        "cases": ("Cases", "Canonical case hubs accepted through provenance review.", []),
        "instruments": (
            "Legal instruments",
            "Canonical instrument hubs accepted through provenance review.",
            [],
        ),
        "families": (
            "Document families",
            "Exact-content families are metadata groupings; they do not imply a legal relationship.",
            family_links,
        ),
        "memos": ("Research memoranda", "Reusable research analyses with cited sources.", []),
    }
    for folder, (title, description, links) in collection_specs.items():
        path = root / "wiki" / folder / "index.md"
        generated = render_frontmatter([
            ("generated_kind", "collection-index"),
            ("generated_fingerprint", FINGERPRINT_TOKEN),
        ]) + "\n\n" + collection_index(title, description, links)
        generated_write(path, generated, protected_reports, stats, "collection-index")
        expected.add(path)
    index_content = render_frontmatter([
        ("generated_kind", "master-index"), ("generated_fingerprint", FINGERPRINT_TOKEN)
    ]) + "\n\n" + master_index(records, dimension_spec)
    generated_write(
        root / "wiki" / "index.md", index_content, protected_reports, stats, "master-index",
        [legacy_v1_master_index(records, dimensions["website"], dimensions["topic"])],
    )
    home_content = render_frontmatter([
        ("generated_kind", "home"), ("generated_fingerprint", FINGERPRINT_TOKEN)
    ]) + "\n\n" + home_markdown(records)
    generated_write(
        root / "wiki" / "home.md", home_content, protected_reports, stats, "home"
    )
    overview_path = root / "wiki" / "overview.md"
    overview_created = legacy_overview_date(overview_path, imported)
    overview_content = render_frontmatter([
        ("generated_kind", "overview"), ("generated_fingerprint", FINGERPRINT_TOKEN)
    ]) + "\n\n" + overview_markdown(records, overview_created, csv_meta)
    generated_write(
        overview_path, overview_content, protected_reports, stats, "overview",
        [legacy_v1_overview(
            records, dimensions["website"], dimensions["topic"],
            stats["duplicate_groups"], stats["short_texts"], overview_created, csv_meta,
        )],
    )
    clean_stale_generated(root, expected, protected_reports, stats)
    append_import_log(root, imported, csv_meta, stats)
    catalog_path = root / "data" / "catalog.jsonl"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_lines = []
    for record in records:
        payload = {k: v for k, v in record.items() if k not in {"text", "summary"}}
        payload.update({"text_chars": len(record["text"]), "summary_chars": len(record["summary"]),
                        "imported": imported, "csv_path": csv_meta["path"], "csv_sha256": csv_meta["sha256"]})
        catalog_lines.append(json.dumps(payload, ensure_ascii=False))
    write_text(catalog_path, "\n".join(catalog_lines) + ("\n" if catalog_lines else ""))
    report = {
        "csv": csv_meta, "stats": stats, "content_change_reports": raw_reports,
        "protected_conflict_reports": protected_reports,
    }
    write_text(root / "data" / "last_import.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import df_organized.csv into the law wiki.")
    parser.add_argument("--csv", type=Path, default=Path.home() / "Downloads" / "df_organized.csv")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--force-raw", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    csv_path, root = args.csv.expanduser().resolve(), args.root.expanduser().resolve()
    if not csv_path.is_file():
        raise SystemExit(f"CSV not found: {csv_path}")
    report = import_corpus(csv_path, root, force_raw=args.force_raw, limit=args.limit)
    print(json.dumps(report["stats"], indent=2))
    for heading, key in (
        ("Raw content-hash changes (not overwritten):", "content_change_reports"),
        ("Protected wiki conflicts (not overwritten):", "protected_conflict_reports"),
    ):
        if report[key]:
            print(heading)
            for item in report[key]:
                print(f"  {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
