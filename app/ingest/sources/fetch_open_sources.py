#!/usr/bin/env python3
"""Fetch public Portuguese texts for Regulation (EC) No 261/2004.

EUR-Lex HTML is read from the Publications Office CELLAR resource
(https://publications.europa.eu/resource/celex/{CELEX}). The eur-lex.europa.eu
HTML endpoint answers non-browser clients with an AWS WAF challenge, so the
script does not scrape that host. DGSI decisions come from the public Lotus
Notes SearchView of each higher-court database.

Idempotent: an existing raw file with the same content_hash is left in place.
A different content_hash is reported and not overwritten.

    python -m app.ingest.sources.fetch_open_sources --root .
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import import_csv  # noqa: E402

USER_AGENT = "LawWiki-research/1.0 (contact via github.com/Dong-Xuyong)"
MIN_INTERVAL_S = 2.0
IMPORTED_ON = "2026-10-16"
TOPIC = "Transporte aéreo — Regulamento 261/2004"
TOPIC_SLUG = "transporte-aereo-regulamento-261-2004"
MAX_BODY_BYTES = 8_000_000
DGSI_CAP = 40
HTTP_TIMEOUT_S = 60

CATALOG_FIELDS = (
    "id",
    "title",
    "filename",
    "folder",
    "year",
    "website",
    "topic",
    "topic_raw",
    "rel_raw",
    "rel_source",
    "verification",
    "content_hash",
    "text_chars",
    "document_type",
    "kind",
    "source_url",
)

# Leading CELEX first. A later CELEX whose extracted text matches an earlier
# one is the same joined judgment and is not stored twice.
EURLEX_DOCUMENTS: tuple[dict[str, str], ...] = (
    {
        "celex": "32004R0261",
        "website": "EUR-Lex",
        "kind": "legislation",
        "folder": "Fontes abertas/EUR-Lex",
        "filename": "CELEX-32004R0261",
    },
    {
        "celex": "62007CJ0402",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62007CJ0402",
    },
    {
        "celex": "62007CJ0432",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62007CJ0432",
    },
    {
        "celex": "62010CJ0581",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62010CJ0581",
    },
    {
        "celex": "62010CJ0629",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62010CJ0629",
    },
    {
        "celex": "62007CJ0549",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62007CJ0549",
    },
    {
        "celex": "62011CJ0011",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62011CJ0011",
    },
    {
        "celex": "62015CJ0315",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62015CJ0315",
    },
    {
        "celex": "62017CJ0195",
        "website": "TJUE",
        "kind": "case_law",
        "folder": "Fontes abertas/TJUE",
        "filename": "CELEX-62017CJ0195",
    },
)

# View UNIDs are the public "Por Ano" / acórdãos views observed on dgsi.pt.
DGSI_COURTS: tuple[dict[str, str], ...] = (
    {
        "db": "jstj",
        "view": "954f0ce6ad9dd8b980256b5f003fa814",
        "website": "DGSI-STJ",
        "court": "Supremo Tribunal de Justiça",
    },
    {
        "db": "jtrl",
        "view": "33182fc732316039802565fa00497eec",
        "website": "DGSI-TRL",
        "court": "Tribunal da Relação de Lisboa",
    },
    {
        "db": "jtrp",
        "view": "56a6e7121657f91e80257cda00381fdf",
        "website": "DGSI-TRP",
        "court": "Tribunal da Relação do Porto",
    },
    {
        "db": "jtrc",
        "view": "8fe0e606d8f56b22802576c0005637dc",
        "website": "DGSI-TRC",
        "court": "Tribunal da Relação de Coimbra",
    },
    {
        "db": "jtre",
        "view": "134973db04f39bf2802579bf005f080b",
        "website": "DGSI-TRE",
        "court": "Tribunal da Relação de Évora",
    },
    {
        "db": "jtrg",
        "view": "86c25a698e4e7cb7802579ec004d3832",
        "website": "DGSI-TRG",
        "court": "Tribunal da Relação de Guimarães",
    },
)

DGSI_QUERIES = ("261/2004", "Regulamento (CE) n.º 261/2004")

PT_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_SKIP_TAGS = {"script", "style", "noscript", "head"}
_BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr",
    "blockquote", "section", "article", "table", "br",
}


class _HTMLText(HTMLParser):
    """Turn HTML into text, keeping block breaks and dropping chrome."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.banner = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): (value or "") for key, value in attrs}
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if self.banner:
            if tag == "div":
                self.banner += 1
            return
        if tag == "div" and attr.get("id", "").lower() == "banner":
            self.banner = 1
            return
        if self.skip:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self.skip:
            self.skip -= 1
            return
        if self.banner:
            if tag == "div":
                self.banner -= 1
            return
        if self.skip:
            return
        if tag in _BLOCK_TAGS and tag != "br":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip or self.banner:
            return
        self.parts.append(data)


class _TableText(HTMLParser):
    """Read top-level HTML tables as rows of cells, keeping inner line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, str]]] = []
        self._depth = 0
        self._skip = 0
        self._row: list[dict[str, str]] | None = None
        self._cell: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): (value or "") for key, value in attrs}
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == "table":
            self._depth += 1
            return
        if self._skip or self._depth != 1:
            if tag in {"br", "p"} and self._cell is not None:
                self._cell.append("\n")
            return
        if tag == "tr":
            self._row = []
            return
        if tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._href = ""
            self._row.append({"text": "", "href": ""})
            return
        if tag == "a" and self._cell is not None:
            href = attr.get("href", "")
            if "opendocument" in href.casefold():
                self._href = href
            return
        if tag in {"br", "p", "div"} and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
            return
        if tag == "table" and self._depth:
            self._depth -= 1
            return
        if self._depth != 1:
            return
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row[-1] = {"text": "".join(self._cell), "href": self._href}
            self._cell = None
            self._href = ""
            return
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip or self._cell is None:
            return
        self._cell.append(data)


def cleanup_text(text: str) -> str:
    """NFC text with HTML whitespace collapsed and paragraph breaks kept."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    blank = 0
    for line in lines:
        if not line:
            blank += 1
            if blank == 1 and cleaned:
                cleaned.append("")
            continue
        blank = 0
        cleaned.append(line)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    return "\n".join(cleaned)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html or "")
    parser.close()
    return cleanup_text("".join(parser.parts))


def is_challenge_page(html: str) -> bool:
    sample = (html or "")[:4000].casefold()
    return (
        "challenge-container" in sample
        or "awswafintegration" in sample
        or "javascript is disabled" in sample
    )


def is_portuguese(text: str) -> bool:
    sample = (text or "").casefold()
    if len(sample) < 400:
        return False
    portuguese = sum(
        sample.count(token)
        for token in (" de ", " que ", " não ", "artigo", "acórdão", "regulamento", "considerando")
    )
    english = sample.count("judgment of the court") + sample.count(" this regulation ")
    french = sample.count("arrêt") + sample.count("règlement")
    return portuguese >= 4 and portuguese > english and portuguese > french


def mentions_regulation(text: str) -> bool:
    return "261/2004" in (text or "")


def _cell_text(cell: dict[str, str]) -> str:
    return cleanup_text(cell.get("text", ""))


def parse_dgsi_search(html: str, *, website: str, court: str) -> list[dict[str, str]]:
    parser = _TableText()
    parser.feed(html or "")
    parser.close()
    hits: list[dict[str, str]] = []
    for row in parser.rows:
        href = next((cell.get("href", "") for cell in row if cell.get("href")), "")
        if "opendocument" not in href.casefold():
            continue
        texts = [_cell_text(cell) for cell in row]
        texts = [item for item in texts if item]
        if len(texts) < 3:
            continue
        date_raw = next((item for item in texts if parse_dgsi_date(item)), "")
        process = ""
        relator = ""
        descriptors = ""
        # Typical columns: date, process, relator, descriptors.
        rest = [item for item in texts if item != date_raw]
        if rest:
            process = rest[0].split("\n", 1)[0].strip()
        if len(rest) >= 2:
            relator = rest[1].split("\n", 1)[0].strip()
        if len(rest) >= 3:
            descriptors = rest[2]
        hits.append(
            {
                "website": website,
                "court": court,
                "href": href,
                "decision_date": parse_dgsi_date(date_raw),
                "date_raw": date_raw,
                "process_number": process,
                "relator": relator,
                "descriptors": descriptors,
            }
        )
    return hits


def dgsi_document_url(href: str) -> str:
    href = (href or "").replace("&amp;", "&").strip()
    if href.startswith("/"):
        href = "https://www.dgsi.pt" + href
    return href.split("&", 1)[0]


def extract_dgsi(html: str, *, court: str) -> dict[str, str]:
    parser = _TableText()
    parser.feed(html or "")
    parser.close()
    blocks: list[str] = []
    fields: dict[str, str] = {}
    for row in parser.rows:
        cells = [_cell_text(cell) for cell in row]
        cells = [cell for cell in cells if cell and not cell.casefold().startswith("acórdãos ")]
        if not cells:
            continue
        if len(cells) == 1:
            blocks.append(cells[0])
            continue
        label = cells[0].strip()
        value = "\n".join(cells[1:]).strip()
        if not value:
            blocks.append(label)
            continue
        key = label.casefold().rstrip(":").strip()
        if key and key not in fields:
            fields[key] = value
        if "\n" in value:
            blocks.append(f"{label.rstrip()}\n{value}")
        else:
            spacer = "" if label.endswith(":") else ":"
            blocks.append(f"{label.rstrip()}{spacer} {value}".replace(": :", ":"))
    text = cleanup_text("\n\n".join(blocks))
    process = _field(fields, "processo")
    relator = _field(fields, "relator")
    date_raw = _field(fields, "data do acord")
    decision_date = parse_dgsi_date(date_raw)
    year = decision_date[:4] if decision_date else ""
    heading = court
    for block in blocks[:3]:
        if block.casefold().startswith("acórdão"):
            heading = block.split("\n", 1)[0].strip()
            break
    title_process = process or "sem processo"
    title = f"{heading} {title_process}"
    if decision_date:
        title = f"{title} ({decision_date})"
    return {
        "text": text,
        "title": title[:300],
        "process_number": process,
        "relator": relator,
        "decision_date": decision_date,
        "year": year,
        "descriptors": _field(fields, "descritor"),
    }


def _field(fields: dict[str, str], prefix: str) -> str:
    for key, value in fields.items():
        if key.startswith(prefix):
            return value.split("\n", 1)[0].strip()
    return ""


def extract_eurlex(html: str, *, celex: str, kind: str) -> dict[str, str]:
    text = html_to_text(html)
    year = ""
    decision_date = ""
    if kind == "legislation":
        match = re.search(r"(\d{4})", celex)
        year = match.group(1) if match else ""
        decision_date = parse_pt_date(text[:2500])
        if decision_date:
            year = decision_date[:4] or year
    else:
        decision_date = judgment_date(text)
        celex_year = re.search(r"(\d{4})", celex)
        year = decision_date[:4] if decision_date else (celex_year.group(1) if celex_year else "")
    title = eurlex_title(text, celex, kind)
    return {
        "text": text,
        "title": title,
        "process_number": celex,
        "relator": "",
        "decision_date": decision_date,
        "year": year,
        "descriptors": "",
    }


def eurlex_title(text: str, celex: str, kind: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if kind == "legislation":
        for line in lines:
            folded = line.casefold()
            if folded.startswith("regulamento") or folded.startswith("regulation"):
                return line[:300]
        return f"CELEX {celex}"
    case_line = ""
    party = ""
    for index, line in enumerate(lines):
        folded = line.casefold()
        if "processo" in folded and re.search(r"c[\-\u2011]\d", folded):
            case_line = line.rstrip(",").strip()
            for follow in lines[index + 1:index + 10]:
                follow_folded = follow.casefold()
                if follow_folded in {"e", "contra"} or follow_folded.startswith("contra"):
                    break
                if follow_folded.startswith("que tem") or follow_folded.startswith("que têm"):
                    continue
                party = follow.rstrip(",").strip()
                break
            break
    if case_line and party:
        return f"{case_line} — {party}"[:300]
    if case_line:
        return case_line[:300]
    for line in lines:
        if line.startswith("«"):
            return f"CELEX {celex} — {line[:220]}"
    return f"CELEX {celex}"


def judgment_date(text: str) -> str:
    folded = (text or "").casefold()
    marker = folded.find("acórdão do tribunal")
    window = text[marker:marker + 800] if marker >= 0 else text[:8000]
    found = parse_pt_date(window)
    return found or parse_pt_date(text[:8000])


def parse_pt_date(text: str) -> str:
    match = re.search(r"(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})", text or "", re.IGNORECASE)
    if not match:
        return ""
    month = PT_MONTHS.get(match.group(2).casefold())
    if not month:
        return ""
    try:
        from datetime import date

        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return ""


def parse_dgsi_date(value: str) -> str:
    """Parse a DGSI date. Slash dates follow the search view (MM/DD/YYYY). Hyphen dates follow the decision field (DD-MM-YYYY)."""
    token = (value or "").strip().split("\n", 1)[0].strip()
    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", token)
    hyphen = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", token)
    if slash:
        month, day, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
    elif hyphen:
        day, month, year = int(hyphen.group(1)), int(hyphen.group(2)), int(hyphen.group(3))
    else:
        return ""
    if month > 12 and day <= 12:
        month, day = day, month
    try:
        from datetime import date

        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def parse_us_date(value: str) -> str:
    return parse_dgsi_date(value)


def choose_cellar_item(html: str) -> str:
    """Pick the Portuguese HTML item from a CELLAR 300 Multiple-Choice page."""
    pattern = re.compile(
        r'href="(https?://publications\.europa\.eu/resource/cellar/[^"]+)"[\s\S]{0,600}?title="stream_name">([^<]+)',
        re.IGNORECASE,
    )
    ranked: list[tuple[int, str]] = []
    for href, name in pattern.findall(html or ""):
        folded = name.casefold()
        if not any(token in folded for token in ("_pt", "texte_pt", ".por")):
            continue
        score = 0
        if "ecr" in folded or ("_pt_" in folded and "texte_pt" not in folded):
            score += 8
        if "texte_pt" in folded:
            score += 3
        if folded.endswith(".html"):
            score += 2
        ranked.append((score, href))
    if not ranked:
        return ""
    ranked.sort(reverse=True)
    return ranked[0][1]


def cellar_url(celex: str) -> str:
    return f"https://publications.europa.eu/resource/celex/{celex}"


def dgsi_search_url(db: str, view: str, query: str) -> str:
    quoted = urllib.parse.quote(query)
    return (
        f"https://www.dgsi.pt/{db}.nsf/{view}?SearchView&Query={quoted}"
        "&SearchOrder=4&SearchMax=200&SearchWV=FALSE"
    )


def build_record(
    *,
    website: str,
    folder: str,
    filename: str,
    year: str,
    kind: str,
    title: str,
    text: str,
    source_url: str,
    process_number: str = "",
    relator: str = "",
    decision_date: str = "",
    court: str = "",
) -> dict[str, Any]:
    text = cleanup_text(text)
    website_slug = import_csv.slugify(website, "website")
    file_slug = import_csv.slugify(filename, "document")
    doc_id = import_csv.document_id(website, folder, filename)
    year = (year or "unknown").strip() or "unknown"
    title = re.sub(r"\s+", " ", title).strip()[:300] or filename
    rel_raw = f"raw/documents/opensrc/{website_slug}/{year}/{doc_id}.md"
    rel_source = f"wiki/sources/{file_slug}--{doc_id}.md"
    document_type = "legislation" if kind == "legislation" else "case-law"
    record: dict[str, Any] = {
        "id": doc_id,
        "title": title,
        "filename": filename,
        "folder": folder,
        "year": year,
        "website": website,
        "topic": TOPIC,
        "topic_raw": TOPIC,
        "topic_slug": TOPIC_SLUG,
        "website_slug": website_slug,
        "kind": kind,
        "source_url": source_url,
        "content_hash": import_csv.content_hash(text),
        "text": text,
        "text_chars": len(text),
        "document_type": document_type,
        "rel_raw": rel_raw,
        "rel_source": rel_source,
        "source_slug": f"{file_slug}--{doc_id}",
        "verification": "unverified",
        "process_number": process_number or "unknown",
        "relator": relator or "unknown",
        "decision_date": decision_date or "unknown",
        "court": court or website,
    }
    record["summary"] = neutral_summary(record)
    return record


def neutral_summary(record: dict[str, Any]) -> str:
    kind_pt = "legislação" if record["kind"] == "legislation" else "jurisprudência"
    details: list[str] = []
    if record.get("process_number") and record["process_number"] != "unknown":
        details.append(f"Identificador publicado: {record['process_number']}.")
    if record.get("decision_date") and record["decision_date"] != "unknown":
        details.append(f"Data publicada: {record['decision_date']}.")
    if record.get("relator") and record["relator"] != "unknown":
        details.append(f"Relator publicado: {record['relator']}.")
    if record.get("court"):
        details.append(f"Órgão indicado na origem: {record['court']}.")
    extra = " ".join(details)
    return (
        "Parágrafo não verificado: não é um digest jurídico nem um entendimento do tribunal. "
        f"Documento público de {kind_pt} obtido de {record['website']}, com o título «{record['title']}». "
        f"{extra} O ficheiro raw guarda o texto extraído do HTML publicado em {record['source_url']}, "
        "sem acrescentos. Esta frase não foi conferida como enunciado de direito."
    )


def raw_markdown(record: dict[str, Any]) -> str:
    frontmatter = import_csv.render_frontmatter(
        [
            ("id", record["id"]),
            ("folder", record["folder"]),
            ("filename", record["filename"]),
            ("year", record["year"]),
            ("website", record["website"]),
            ("topic", record["topic"]),
            ("kind", record["kind"]),
            ("source_url", record["source_url"]),
            ("content_hash", record["content_hash"]),
            ("imported", IMPORTED_ON),
        ]
    )
    body = record["text"].replace("\r\n", "\n").replace("\r", "\n")
    return f"{frontmatter}\n\n# {record['title']}\n\n## Full text\n\n{body}\n"


def source_markdown(record: dict[str, Any]) -> str:
    jurisdiction = "Portugal" if str(record["website"]).startswith("DGSI-") else "unknown"
    jurisdiction_source = "source-text" if jurisdiction == "Portugal" else "unset"
    frontmatter = import_csv.render_frontmatter(
        [
            ("tags", ["sources", record["topic_slug"], record["website_slug"]]),
            ("id", record["id"]),
            ("title", record["title"]),
            ("aliases", [record["id"], record["filename"]]),
            ("folder", record["folder"]),
            ("filename", record["filename"]),
            ("year", record["year"]),
            ("website", record["website"]),
            ("topic", record["topic"]),
            ("topic_raw", record["topic_raw"]),
            ("topic_kind", "unmapped"),
            ("sector", ""),
            ("categories", []),
            ("document_type", record["document_type"]),
            ("process_number", record["process_number"]),
            ("case", record["filename"]),
            ("forum", record["court"]),
            ("decision_date", record["decision_date"]),
            ("sectors", []),
            ("doctrines", []),
            ("cited_instruments", []),
            ("outcome_status", "unknown"),
            ("duplicate_of", []),
            ("family", ""),
            ("jurisdiction", jurisdiction),
            ("jurisdiction_source", jurisdiction_source),
            ("authority_level", "unknown"),
            ("citation", record["filename"]),
            ("legal_status", "unknown"),
            ("as_of", record["year"]),
            ("verification", "unverified"),
            ("enriched", False),
            ("enrichment_state", "imported-unverified"),
            ("extractor_version", "lawwiki-opensrc:1"),
            ("summary_hash", import_csv.content_hash(record["summary"])),
            ("content_hash", record["content_hash"]),
            ("kind", record["kind"]),
            ("source_url", record["source_url"]),
            ("raw", record["rel_raw"]),
            ("created", IMPORTED_ON),
            ("updated", IMPORTED_ON),
        ]
    )
    raw_link = record["rel_raw"].removesuffix(".md")
    return (
        f"{frontmatter}\n\n# {record['title']}\n\n## Status\n\n"
        "**Unverified** description. Research aid, not legal advice. "
        f"Check [[{raw_link}|the raw document]] before relying on it.\n\n"
        f"## Summary\n\n{record['summary']}\n\n"
        "## Source metadata\n\n"
        f"- Organization: {record['website']}\n"
        f"- Topic (raw exact label): {record['topic_raw']}\n"
        f"- Folder: `{record['folder']}`\n"
        f"- Filename: `{record['filename']}`\n"
        f"- Year: {record['year']}\n"
        f"- Kind: {record['kind']}\n"
        f"- Source URL: {record['source_url']}\n"
        f"- Process / CELEX: {record['process_number']}\n"
        f"- Decision date: {record['decision_date']}\n"
        f"- Relator: {record['relator']}\n\n"
        "## Key holdings / issues\n\nUnknown until verified against the raw text.\n\n"
        "## Entities mentioned\n\n- None extracted.\n\n"
        "## Concepts\n\n- None extracted.\n\n"
        "## Pinpoint quotations\n\n- None extracted.\n\n"
        "## Related sources\n\n- None established.\n\n"
        f"## Raw source\n\n- [[{raw_link}]] — immutable full text\n"
    )


def catalog_row(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in CATALOG_FIELDS}


def commit_record(root: Path, record: dict[str, Any]) -> dict[str, str]:
    digest = import_csv.content_hash(record["text"])
    if digest != record["content_hash"]:
        raise ValueError("content_hash does not match text")
    raw_path = root / record["rel_raw"]
    state = import_csv.raw_change_state(raw_path, record["content_hash"])
    if state == "changed":
        return {"raw": "changed", "wiki": "skipped"}
    wiki_path = root / record["rel_source"]
    wiki_body = source_markdown(record)
    if state == "unchanged":
        wiki_state = _write_if_absent_or_same(wiki_path, wiki_body)
        return {"raw": "unchanged", "wiki": wiki_state}
    import_csv.write_text(raw_path, raw_markdown(record))
    wiki_state = _write_if_absent_or_same(wiki_path, wiki_body)
    return {"raw": "written", "wiki": wiki_state}


def _write_if_absent_or_same(path: Path, content: str) -> str:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current.replace("\r\n", "\n").replace("\r", "\n") == content:
            return "unchanged"
        return "protected"
    import_csv.write_text(path, content)
    return "written"


def write_catalog(root: Path, records: Iterable[dict[str, Any]]) -> int:
    rows = [catalog_row(record) for record in records]
    rows.sort(key=lambda row: (str(row["website"]).casefold(), str(row["year"]), str(row["filename"]), str(row["id"])))
    path = root / "data" / "open-sources-catalog.jsonl"
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    import_csv.write_text(path, body)
    return len(rows)


def load_catalog(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "data" / "open-sources-catalog.jsonl"
    if not path.exists():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[str(row["id"])] = row
    return rows


def robots_allowed(status: int, body: str, url: str, user_agent: str = USER_AGENT) -> bool:
    """Decide from a robots.txt response. 404 means no file, so fetching is allowed."""
    if status == 404:
        return True
    if status >= 500:
        return False
    parser = urllib.robotparser.RobotFileParser()
    parser.parse((body or "").splitlines())
    return parser.can_fetch(user_agent, url)


def decode_html(body: bytes, content_type: str) -> str:
    payload = body[3:] if body.startswith(b"\xef\xbb\xbf") else body
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        pass
    match = re.search(r"charset=([\w.-]+)", content_type or "", re.IGNORECASE)
    if match:
        try:
            return payload.decode(match.group(1))
        except (LookupError, UnicodeDecodeError):
            pass
    return payload.decode("iso-8859-1")


class CachedFetcher:
    """Polite HTTP GET with a file cache and a per-host delay."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last: dict[str, float] = {}
        self._robots: dict[str, tuple[int, str]] = {}

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = import_csv.content_hash(url)
        return self.cache_dir / f"{digest}.meta.json", self.cache_dir / f"{digest}.body"

    def fetch(self, url: str) -> dict[str, Any]:
        cached = self._read_cache(url)
        if cached is not None:
            return cached
        if not url.endswith("/robots.txt"):
            allowed, reason = self._allowed(url)
            if not allowed:
                return {
                    "url": url,
                    "status": 0,
                    "final_url": url,
                    "content_type": "",
                    "body": b"",
                    "from_cache": False,
                    "error": reason,
                }
        return self._network(url)

    def _read_cache(self, url: str) -> dict[str, Any] | None:
        meta_path, body_path = self._paths(url)
        if not (meta_path.exists() and body_path.exists()):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["from_cache"] = True
        meta["body"] = body_path.read_bytes()
        meta["error"] = ""
        return meta

    def _network(self, url: str) -> dict[str, Any]:
        meta_path, body_path = self._paths(url)
        host = urllib.parse.urlparse(url).netloc
        self._pause(host)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt,por;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
                status = int(response.status)
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            final_url = exc.geturl()
            content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
            body = exc.read(MAX_BODY_BYTES + 1) if exc.fp else b""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "url": url,
                "status": 0,
                "final_url": url,
                "content_type": "",
                "body": b"",
                "from_cache": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        meta = {
            "url": url,
            "status": status,
            "final_url": final_url,
            "content_type": content_type,
            "fetched_on": IMPORTED_ON,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        body_path.write_bytes(body)
        meta["from_cache"] = False
        meta["body"] = body
        meta["error"] = ""
        return meta

    def _pause(self, host: str) -> None:
        previous = self._last.get(host)
        now = time.monotonic()
        if previous is not None:
            wait = MIN_INTERVAL_S - (now - previous)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    def _allowed(self, url: str) -> tuple[bool, str]:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        if parsed.netloc not in self._robots:
            response = self._read_cache(robots_url) or self._network(robots_url)
            if response.get("error") and not response.get("status"):
                # No rules were published. A later document request still has to succeed on its own.
                self._robots[parsed.netloc] = (404, "")
            else:
                html = decode_html(response.get("body") or b"", response.get("content_type", ""))
                self._robots[parsed.netloc] = (int(response.get("status") or 0), html)
        status, body = self._robots[parsed.netloc]
        if not robots_allowed(status, body, url):
            return False, f"robots.txt disallows {url} (status {status})"
        return True, ""


def _response_html(response: dict[str, Any]) -> str:
    body = response.get("body") or b""
    if len(body) > MAX_BODY_BYTES:
        return ""
    return decode_html(body, str(response.get("content_type") or ""))


def _skip(report: dict[str, Any], reason: str, **fields: str) -> None:
    item = {"reason": reason, **fields}
    report["skipped"].append(item)
    print(f"skip {reason} {fields.get('celex') or fields.get('process_number') or fields.get('url', '')}", file=sys.stderr)


def fetch_open_sources(root: Path) -> dict[str, Any]:
    root = root.resolve()
    fetcher = CachedFetcher(root / "build" / "opensrc-cache")
    existing = load_catalog(root)
    report: dict[str, Any] = {
        "written": [],
        "unchanged": [],
        "changed": [],
        "skipped": [],
        "wiki_protected": [],
        "documents": [],
    }
    kept: dict[str, dict[str, Any]] = {}
    seen_hashes: dict[str, str] = {}

    for spec in EURLEX_DOCUMENTS:
        url = cellar_url(spec["celex"])
        print(f"fetch {url}", file=sys.stderr)
        response = fetcher.fetch(url)
        if int(response.get("status") or 0) == 300:
            choice = choose_cellar_item(_response_html(response))
            if choice:
                print(f"fetch {choice}", file=sys.stderr)
                chosen = fetcher.fetch(choice)
                if int(chosen.get("status") or 0) == 200:
                    response = chosen
                    url = choice
        if response.get("error"):
            _skip(report, response["error"], celex=spec["celex"], url=url)
            continue
        if int(response.get("status") or 0) != 200:
            _skip(report, f"HTTP {response.get('status')}", celex=spec["celex"], url=url)
            continue
        html = _response_html(response)
        if not html or is_challenge_page(html):
            _skip(report, "EUR-Lex HTML unavailable (challenge or empty body)", celex=spec["celex"], url=url)
            continue
        extracted = extract_eurlex(html, celex=spec["celex"], kind=spec["kind"])
        if not is_portuguese(extracted["text"]):
            _skip(report, "Portuguese text unavailable", celex=spec["celex"], url=url)
            continue
        text_hash = import_csv.content_hash(extracted["text"])
        prior = seen_hashes.get(text_hash)
        if prior:
            _skip(report, f"same text as {prior}", celex=spec["celex"], url=url)
            continue
        seen_hashes[text_hash] = spec["celex"]
        source_url = str(response.get("final_url") or url)
        record = build_record(
            website=spec["website"],
            folder=spec["folder"],
            filename=spec["filename"],
            year=extracted["year"],
            kind=spec["kind"],
            title=extracted["title"],
            text=extracted["text"],
            source_url=source_url,
            process_number=spec["celex"],
            decision_date=extracted["decision_date"],
            court="Jornal Oficial / EUR-Lex" if spec["kind"] == "legislation" else "Tribunal de Justiça da União Europeia",
        )
        _store(root, record, kept, existing, report)

    hits = _dgsi_hits(fetcher, report)
    hits.sort(key=lambda item: (item["score"], item["decision_date"], item["process_number"]), reverse=True)
    chosen_hits: list[dict[str, Any]] = []
    seen_processes: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit["website"], hit["process_number"].casefold(), hit["decision_date"])
        if hit["process_number"] and key in seen_processes:
            _skip(
                report,
                "duplicate process number; kept the higher-ranked copy",
                process_number=hit["process_number"],
                website=hit["website"],
                url=hit["url"],
            )
            continue
        if hit["process_number"]:
            seen_processes.add(key)
        chosen_hits.append(hit)
    selected = chosen_hits[:DGSI_CAP]
    if len(chosen_hits) > DGSI_CAP:
        for extra in chosen_hits[DGSI_CAP:]:
            _skip(
                report,
                f"over the {DGSI_CAP}-decision cap",
                process_number=extra["process_number"],
                website=extra["website"],
                url=extra["url"],
            )
    for hit in selected:
        print(f"fetch {hit['url']}", file=sys.stderr)
        response = fetcher.fetch(hit["url"])
        if response.get("error"):
            _skip(report, response["error"], process_number=hit["process_number"], website=hit["website"], url=hit["url"])
            continue
        if int(response.get("status") or 0) != 200:
            _skip(report, f"HTTP {response.get('status')}", process_number=hit["process_number"], website=hit["website"], url=hit["url"])
            continue
        html = _response_html(response)
        if not html or is_challenge_page(html):
            _skip(report, "empty DGSI document", process_number=hit["process_number"], website=hit["website"], url=hit["url"])
            continue
        extracted = extract_dgsi(html, court=hit["court"])
        if not extracted["text"] or not mentions_regulation(extracted["text"]):
            _skip(
                report,
                "full text does not contain 261/2004",
                process_number=hit["process_number"],
                website=hit["website"],
                url=hit["url"],
            )
            continue
        filename = extracted["process_number"] or hit["process_number"] or hit["url"].rstrip("/").split("/")[-1]
        if extracted["decision_date"]:
            filename = f"{filename} {extracted['decision_date']}"
        record = build_record(
            website=hit["website"],
            folder=f"Fontes abertas/{hit['website']}",
            filename=filename,
            year=extracted["year"] or (hit["decision_date"][:4] if hit["decision_date"] else "unknown"),
            kind="case_law",
            title=extracted["title"],
            text=extracted["text"],
            source_url=str(response.get("final_url") or hit["url"]),
            process_number=extracted["process_number"] or hit["process_number"],
            relator=extracted["relator"] or hit["relator"],
            decision_date=extracted["decision_date"] or hit["decision_date"],
            court=hit["court"],
        )
        _store(root, record, kept, existing, report)

    # Keep previously catalogued rows whose raw file is still present when this
    # run refused an overwrite, so the catalog continues to describe the disk.
    for doc_id, row in existing.items():
        if doc_id in kept:
            continue
        rel = str(row.get("rel_raw") or "")
        if rel and (root / rel).is_file():
            kept[doc_id] = _record_from_catalog_row(row)

    count = write_catalog(root, kept.values())
    report["catalog_rows"] = count
    report["documents"] = [
        {
            "website": record["website"],
            "title": record["title"],
            "id": record["id"],
            "year": record["year"],
            "chars": record["text_chars"],
        }
        for record in sorted(kept.values(), key=lambda item: (item["website"], item["year"], item["id"]))
    ]
    return report


def _record_from_catalog_row(row: dict[str, Any]) -> dict[str, Any]:
    record = {key: row.get(key, "") for key in CATALOG_FIELDS}
    record["text_chars"] = int(row.get("text_chars") or 0)
    return record


def _store(
    root: Path,
    record: dict[str, Any],
    kept: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    report: dict[str, Any],
) -> None:
    outcome = commit_record(root, record)
    if outcome["wiki"] == "protected":
        report["wiki_protected"].append(record["rel_source"])
    if outcome["raw"] == "changed":
        report["changed"].append(
            {
                "id": record["id"],
                "rel_raw": record["rel_raw"],
                "new_content_hash": record["content_hash"],
            }
        )
        previous = existing.get(record["id"])
        if previous:
            kept[record["id"]] = _record_from_catalog_row(previous)
        return
    kept[record["id"]] = record
    bucket = "written" if outcome["raw"] == "written" else "unchanged"
    report[bucket].append(record["id"])


def _dgsi_hits(fetcher: CachedFetcher, report: dict[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for court in DGSI_COURTS:
        court_hits = 0
        for query in DGSI_QUERIES:
            url = dgsi_search_url(court["db"], court["view"], query)
            print(f"fetch {url}", file=sys.stderr)
            response = fetcher.fetch(url)
            if response.get("error"):
                _skip(report, response["error"], website=court["website"], url=url)
                continue
            status = int(response.get("status") or 0)
            if status == 404:
                _skip(report, "search view not found", website=court["website"], url=url)
                continue
            if status != 200:
                _skip(report, f"HTTP {status}", website=court["website"], url=url)
                continue
            html = _response_html(response)
            if is_challenge_page(html):
                _skip(report, "DGSI search challenged", website=court["website"], url=url)
                continue
            for hit in parse_dgsi_search(html, website=court["website"], court=court["court"]):
                doc_url = dgsi_document_url(hit["href"])
                court_hits += 1
                if doc_url in found:
                    continue
                desc = hit["descriptors"].casefold()
                score = 0
                if "aéreo" in desc or "aereo" in desc:
                    score += 5
                if any(token in desc for token in ("indemn", "atraso", "cancel", "embarque", "passageir")):
                    score += 3
                if court["website"] == "DGSI-STJ":
                    score += 2
                found[doc_url] = {
                    "url": doc_url,
                    "website": court["website"],
                    "court": court["court"],
                    "process_number": hit["process_number"],
                    "relator": hit["relator"],
                    "decision_date": hit["decision_date"],
                    "descriptors": hit["descriptors"],
                    "score": score,
                }
        if court_hits == 0:
            _skip(report, "no DGSI search hits for 261/2004", website=court["website"], url=court["db"])
    return list(found.values())


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Fetch open-source Regulation 261/2004 texts into the law wiki.")
    parser.add_argument("--root", type=Path, default=_ROOT)
    args = parser.parse_args(argv)
    report = fetch_open_sources(args.root)
    public = {
        "catalog_rows": report["catalog_rows"],
        "written": len(report["written"]),
        "unchanged": len(report["unchanged"]),
        "changed": report["changed"],
        "skipped": report["skipped"],
        "wiki_protected": report["wiki_protected"],
        "documents": report["documents"],
    }
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
