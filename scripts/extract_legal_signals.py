#!/usr/bin/env python3
"""Deterministic, evidence-preserving legal-signal extraction.

The extractor deliberately produces candidates, not verified legal facts.  All
offsets are Python Unicode code-point, half-open offsets into ``full_text``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

EXTRACTOR_VERSION = "legal-signals-v1"
DEFAULT_WINDOW = 900
MAX_NEIGHBORS = 3

MONTHS = (
    "janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|"
    "setembro|outubro|novembro|dezembro"
)
PROCESS_RE = re.compile(
    r"(?i)\b(?:processo|proc\.?)\s*(?:n[.º°o]*\s*)?"
    r"(?P<value>[0-9][0-9A-Za-z./º°\-_]{2,}(?:\s*[-–]\s*[A-Za-z0-9.]+)?)"
)
ECLI_RE = re.compile(r"(?i)\bECLI:[A-Z]{2}:[A-Z0-9.]+:[0-9]{4}:[A-Z0-9.:-]+\b")
DATE_RE = re.compile(
    rf"(?ix)\b(?:"
    rf"(?:0?[1-9]|[12][0-9]|3[01])\s+de\s+(?:{MONTHS})\s+de\s+[12][0-9]{{3}}"
    rf"|(?:0?[1-9]|[12][0-9]|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.][12][0-9]{{3}}"
    rf")\b"
)
ARTICLE_RE = re.compile(
    r"(?ix)\b(?:art(?:igo|\.)?|arts?\.?)\s*"
    r"(?P<articles>\d+(?:\s*[.º°o]+)?(?:\s*[,e]\s*\d+(?:\s*[.º°o]+)?)*)"
    r"(?:\s*,?\s*(?:n[.º°o]*\s*\d+(?:\s*,?\s*al(?:ínea|\.)?\s*[a-z]\))?))?"
    r"(?:\s+(?:do|da|dos|das)\s+"
    r"(?P<instrument>(?:Código|Regulamento|Decreto(?:-Lei)?|Lei|Portaria|"
    r"Constituição|Convenção|Diretiva)[^.;:\n]{0,100}))?"
)
INSTRUMENT_RE = re.compile(
    r"(?ix)\b(?:"
    r"(?:Decreto-?Lei|Lei|Portaria)\s+n?[.º°o]*\s*\d+(?:/\d{2,4})?"
    r"|Regulamento\s*(?:\([A-Z]{2}\)\s*)?(?:n?[.º°o]*\s*)?\d+(?:/\d{2,4})?"
    r"|Código\s+(?:Civil|Penal|de\s+Processo\s+(?:Civil|Penal)|do\s+Trabalho)"
    r"|Constituição\s+da\s+República\s+Portuguesa"
    r")\b"
)
TYPE_PATTERNS = (
    ("acórdão", re.compile(r"(?im)^\s*ac[oó]rd[aã]o\b")),
    ("sentença", re.compile(r"(?im)^\s*senten[cç]a(?:\s+n[.º°o]*)?\b")),
    ("decisão", re.compile(r"(?im)^\s*decis[aã]o\b")),
    ("despacho", re.compile(r"(?im)^\s*despacho\b")),
    ("parecer", re.compile(r"(?im)^\s*parecer\b")),
    ("legislation", re.compile(r"(?im)^\s*(?:lei|decreto-?lei|portaria)\s+n?[.º°o]*\s*\d")),
)
FORUM_RE = re.compile(
    r"(?im)^[^\n]{0,30}(?:tribunal|centro de arbitragem|supremo tribunal|"
    r"relação de|julgado de paz)[^\n]{0,180}$"
)
DISPOSITION_RE = re.compile(
    r"(?im)^\s*(?:decis[aã]o|dispositivo|delibera[cç][aã]o|"
    r"nestes termos|decide-se|julga-se)\s*:?\s*$"
)
TOKEN_RE = re.compile(r"(?u)\b[^\W\d_]{3,}\b")
PARTY_RE = re.compile(
    r"(?i)\b(?:reclamante|reclamada?|requerente|requerida?|autor(?:a)?|réu|ré|partes?)\b"
)
LAW_RE = re.compile(r"(?i)\b(?:direito aplicável|fundamentação de direito|enquadramento jurídico)\b")


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_full_text(raw_markdown: str) -> str:
    """Return the normalized payload after the first exact Full text heading.

    One Markdown separator newline and the importer's framing newline are
    removed. Payload whitespace is otherwise retained. This is the same
    coordinate contract used by the connection-graph validator.
    """

    normalized = normalize_newlines(raw_markdown)
    match = re.search(r"(?m)^## Full text[ \t]*\n", normalized)
    if not match:
        raise ValueError("raw markdown has no '## Full text' heading")
    payload = normalized[match.end() :]
    if payload.startswith("\n"):
        payload = payload[1:]
    return payload[:-1] if payload.endswith("\n") else payload


def _span(text: str, start: int, end: int) -> dict[str, Any]:
    quote = text[start:end]
    digest = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    return {
        "start": start,
        "end": end,
        "quote": quote,
        "sha256": digest,
        "evidence_hash": digest,
    }


def _candidate(
    text: str, kind: str, value: str, start: int, end: int, **extra: Any
) -> dict[str, Any]:
    result = {
        "kind": kind,
        "value": value,
        "extractor_version": EXTRACTOR_VERSION,
        "provenance": _span(text, start, end),
    }
    result.update(extra)
    return result


def _matches(
    text: str, pattern: re.Pattern[str], kind: str, group: str | int = 0
) -> list[dict[str, Any]]:
    found = []
    seen: set[tuple[int, int, str]] = set()
    for match in pattern.finditer(text):
        start, end = match.span(group)
        value = match.group(group).strip()
        key = (start, end, value.casefold())
        if key not in seen:
            seen.add(key)
            found.append(_candidate(text, kind, value, start, end))
    return found


def extract_signals(
    full_text: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Extract deterministic legal candidates from an already parsed payload."""

    text = normalize_newlines(full_text)
    metadata = metadata or {}
    document_types: list[dict[str, Any]] = []
    for value, pattern in TYPE_PATTERNS:
        match = pattern.search(text[:5000])
        if match:
            document_types.append(
                _candidate(text, "document_type", value, match.start(), match.end())
            )

    citations = _matches(text, ARTICLE_RE, "article_citation")
    citations.extend(_matches(text, INSTRUMENT_RE, "legal_instrument"))
    citations.sort(key=lambda item: (item["provenance"]["start"], item["kind"], item["value"]))

    dispositions: list[dict[str, Any]] = []
    disposition_matches = list(DISPOSITION_RE.finditer(text))
    if disposition_matches:
        marker = disposition_matches[-1]
        end = min(len(text), marker.start() + 5000)
        dispositions.append(
            _candidate(
                text,
                "decision_tail",
                text[marker.start() : end],
                marker.start(),
                end,
                truncated=end < len(text),
            )
        )

    process_numbers = _matches(text, PROCESS_RE, "process_number", "value")
    evidence = {
        "document_id": metadata.get("id"),
        "catalog_content_hash": metadata.get("content_hash"),
        "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "content_hash_matches_payload": (
            metadata.get("content_hash")
            == hashlib.sha256(text.encode("utf-8")).hexdigest()
            if metadata.get("content_hash")
            else None
        ),
    }
    return {
        "extractor_version": EXTRACTOR_VERSION,
        "offset_contract": "python-unicode-code-point-half-open; normalized-full-text-payload",
        "full_text_chars": len(text),
        "evidence": evidence,
        "document_types": document_types,
        "forums": _matches(text[:5000], FORUM_RE, "forum"),
        "process_numbers": process_numbers,
        "dates": _matches(text, DATE_RE, "date"),
        "ecli": _matches(text, ECLI_RE, "ecli"),
        "citations": citations,
        "dispositions": dispositions,
        "process_keys": sorted({_fold(item["value"]) for item in process_numbers}),
        "ocr_poor": ocr_poor(text),
    }


def parse_and_extract(raw_markdown: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return extract_signals(parse_full_text(raw_markdown), metadata)


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", value)


def ocr_poor(text: str) -> bool:
    """A conservative, deterministic OCR-quality flag."""

    if not text.strip():
        return True
    replacement = text.count("\ufffd")
    words = re.findall(r"(?u)\S+", text)
    broken = sum(bool(re.search(r"(?:[|]{2,}|[_]{4,}|[^\w\s.,;:()/%€ºª-]{3,})", word)) for word in words)
    alpha = sum(char.isalpha() for char in text)
    return replacement >= 2 or (words and broken / len(words) >= 0.08) or alpha / len(text) < 0.35


def exact_duplicate_groups(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        content_hash = str(record.get("content_hash", ""))
        if content_hash:
            groups[content_hash].append(str(record["id"]))
    return [
        {"kind": "exact-content", "key": key, "ids": sorted(ids)}
        for key, ids in sorted(groups.items())
        if len(ids) > 1
    ]


def conservative_families(
    records: Iterable[dict[str, Any]],
    payloads: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Find high-precision filename and normalized-content families."""

    rows = list(records)
    families: list[dict[str, Any]] = []
    by_name: dict[str, list[str]] = defaultdict(list)
    for record in rows:
        stem = Path(str(record.get("filename", ""))).stem
        key = _fold(re.sub(r"(?i)(?:\s*[-_(]?\s*(?:copy|c[oó]pia|duplicado)\s*\d*\s*[)]?)$", "", stem))
        # Four characters still excludes extension-only/noise names while
        # retaining legitimate short case labels (for example "Caso").
        if len(key) >= 4:
            by_name[key].append(str(record["id"]))
    for key, ids in sorted(by_name.items()):
        if len(ids) > 1:
            families.append({"kind": "filename", "key": key, "ids": sorted(ids)})

    if payloads:
        by_content: dict[str, list[str]] = defaultdict(list)
        for doc_id, payload in payloads.items():
            canonical = re.sub(r"\s+", " ", normalize_newlines(payload)).strip().casefold()
            if len(canonical) >= 100:
                key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                by_content[key].append(doc_id)
        for key, ids in sorted(by_content.items()):
            if len(ids) > 1:
                families.append({"kind": "normalized-content", "key": key, "ids": sorted(ids)})
    return families


def _window(text: str, start: int, end: int, size: int) -> dict[str, Any]:
    center = (start + end) // 2
    left = max(0, center - size // 2)
    right = min(len(text), left + size)
    left = max(0, right - size)
    return _span(text, left, right)


def build_packet(
    record: dict[str, Any],
    text: str,
    signals: dict[str, Any],
    neighbors: list[dict[str, Any]] | None = None,
    window_chars: int = DEFAULT_WINDOW,
) -> dict[str, Any]:
    if window_chars < 100:
        raise ValueError("window_chars must be at least 100")
    normalized = normalize_newlines(text)
    windows: dict[str, list[dict[str, Any]]] = {
        "header": [_span(normalized, 0, min(len(normalized), window_chars))],
        "party": [],
        "applicable_law": [],
        "citation": [],
        "disposition": [],
    }
    specs = (
        ("party", list(PARTY_RE.finditer(normalized))[:2]),
        ("applicable_law", list(LAW_RE.finditer(normalized))[:2]),
    )
    for name, matches in specs:
        windows[name] = [_window(normalized, m.start(), m.end(), window_chars) for m in matches]
    windows["citation"] = [
        _window(normalized, item["provenance"]["start"], item["provenance"]["end"], window_chars)
        for item in signals.get("citations", [])[:4]
    ]
    windows["disposition"] = [
        _window(normalized, item["provenance"]["start"], item["provenance"]["end"], window_chars)
        for item in signals.get("dispositions", [])[:1]
    ]
    candidate_keys = (
        "document_types",
        "forums",
        "process_numbers",
        "dates",
        "ecli",
        "citations",
        "dispositions",
        "process_keys",
        "ocr_poor",
    )
    return {
        "id": record["id"],
        "extractor_version": EXTRACTOR_VERSION,
        "metadata": {
            key: record.get(key)
            for key in (
                "rel_raw",
                "rel_source",
                "filename",
                "folder",
                "website",
                "topic",
                "year",
                "content_hash",
            )
        },
        "evidence": signals["evidence"],
        "deterministic_candidates": {
            key: signals.get(key)
            for key in candidate_keys
        },
        "windows": windows,
        "neighbor_candidates": (neighbors or [])[:MAX_NEIGHBORS],
    }


def lexical_neighbors(
    records: list[dict[str, Any]], payloads: dict[str, str], maximum: int = MAX_NEIGHBORS
) -> dict[str, list[dict[str, Any]]]:
    """Return sparse deterministic Jaccard neighbors without third-party code."""

    maximum = max(0, min(MAX_NEIGHBORS, maximum))
    document_tokens: dict[str, set[str]] = {}
    frequencies: Counter[str] = Counter()
    for record in records:
        doc_id = str(record["id"])
        tokens = set(_fold(token) for token in TOKEN_RE.findall(payloads.get(doc_id, "")))
        tokens.discard("")
        document_tokens[doc_id] = tokens
        frequencies.update(tokens)
    sparse = {
        doc_id: {token for token in tokens if frequencies[token] <= max(2, len(records) // 5)}
        for doc_id, tokens in document_tokens.items()
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for doc_id in sorted(sparse):
        scored = []
        for other in sorted(sparse):
            if other == doc_id:
                continue
            union = sparse[doc_id] | sparse[other]
            overlap = sparse[doc_id] & sparse[other]
            if overlap and union:
                scored.append((len(overlap) / len(union), len(overlap), other))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        result[doc_id] = [
            {"id": other, "score": round(score, 8), "shared_sparse_terms": overlap}
            for score, overlap, other in scored[:maximum]
        ]
    return result


def load_catalog(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/enrichment"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional pilot manifest. Review packets and lexical neighbors are generated only for these documents.",
    )
    parser.add_argument("--window-chars", type=int, default=DEFAULT_WINDOW)
    args = parser.parse_args()
    root = args.root.resolve()
    catalog_path = args.catalog if args.catalog.is_absolute() else root / args.catalog
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    records = load_catalog(catalog_path)
    payloads: dict[str, str] = {}
    signals_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        raw_path = root / record["rel_raw"]
        payload = parse_full_text(raw_path.read_text(encoding="utf-8"))
        payloads[record["id"]] = payload
        signals_by_id[record["id"]] = extract_signals(payload, record)
    signal_rows = [dict({"id": row["id"]}, **signals_by_id[row["id"]]) for row in records]
    write_jsonl(output / "legal-signals.jsonl", signal_rows)
    groups = exact_duplicate_groups(records) + conservative_families(records, payloads)
    (output / "document-families.json").write_text(
        json.dumps(groups, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    packet_count = 0
    if args.manifest is not None:
        manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
        manifest = load_catalog(manifest_path)
        manifest_ids = {row["id"] for row in manifest}
        selected = [row for row in records if row["id"] in manifest_ids]
        if len(selected) != len(manifest_ids):
            missing = sorted(manifest_ids - {row["id"] for row in selected})
            raise SystemExit(f"manifest ids missing from catalog: {missing}")
        neighbors = lexical_neighbors(selected, {row["id"]: payloads[row["id"]] for row in selected})
        packets = [
            build_packet(
                row,
                payloads[row["id"]],
                signals_by_id[row["id"]],
                neighbors[row["id"]],
                args.window_chars,
            )
            for row in selected
        ]
        write_jsonl(output / "review-packets.jsonl", packets)
        packet_count = len(packets)
    print(json.dumps({
        "documents": len(records),
        "packets": packet_count,
        "output": str(output),
        "extractor_version": EXTRACTOR_VERSION,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
