#!/usr/bin/env python3
"""Scale the legal connection graph in deterministic tranches.

The pilot (250 documents) stays where it is. ``select`` takes the next catalog
documents that are not already in the pilot or an earlier tranche. ``packets``
reuses the legal-signal packet builder. ``check`` confirms every raw-span
quote against the normalized full-text payload and a packet window. ``build``
adjudicates the pilot plus every tranche, so accepted pilot edges stay put.

Selection is idempotent: repeating ``select`` with the same size and seed
rewrites the open tranche instead of allocating another one. A tranche is
sealed once it has an ``extractor-*.jsonl`` file; the next ``select`` then
starts the following tranche.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import build_connection_graph as graph
import extract_legal_signals as signals
import select_pilot

BATCH_SIZE = 25
TRANCHE_RE = re.compile(r"^t(\d{3})$")
SCHEMA_VERSION = "2.0"
EXTRACTOR_VERSION = "grok-4.7-tranche-v1"
WINDOW_SECTION = {
    "header": "header",
    "party": "parties",
    "applicable_law": "applicable-law",
    "citation": "applicable-law",
    "disposition": "disposition",
}
ARBITRATION_SITES = {"CACCL", "CICAP", "CIAB", "CNIACC", "Triave"}
FORUMS = (
    ("cniacc", "CNIACC", re.compile(r"\bCNIACC\b", re.I)),
    ("cicap", "CICAP", re.compile(r"\bCICAP\b", re.I)),
    ("ciab", "CIAB", re.compile(r"\bCIAB\b", re.I)),
    ("triave", "TRIAVE", re.compile(r"\bTRIAVE\b", re.I)),
    ("caccl", "CACCL", re.compile(r"\bCACCL\b", re.I)),
)
PROCESS_RE = re.compile(
    r"(?i)\b(?:processo|proc\.?)\s*(?:de\s+reclama[cç][aã]o\s+)?"
    r"(?:n[.º°o]*\s*)?(?P<num>\d{1,6}\s*/\s*(?:19|20)\d{2})\b"
)
ADJUDICATIVE_RE = re.compile(r"(?i)tribunal|arbitragem|julgado\s+de\s+paz")
LAW_RE = re.compile(
    r"(?i)\b(Decreto-?Lei|Lei|Portaria)\s+n?[.º°o]*\s*(\d{1,5}\s*/\s*\d{2,4})\b"
)
DECRETO_PREFIX_RE = re.compile(r"(?i)(?:decreto\s*-?\s*|dec\.\s*)$")
REG_RE = re.compile(
    r"(?i)\bRegulamento\s*(?:\((CE|UE|EU)\)\s*)?(?:n?[.º°o]*\s*)?(\d{1,5}\s*/\s*\d{2,4})\b"
)
CODE_RE = re.compile(
    r"(?i)\b(Código\s+Civil|Código\s+Penal|Código\s+de\s+Processo\s+Civil|"
    r"Código\s+de\s+Processo\s+Penal)\b"
)
ART_RE = re.compile(
    r"(?i)\bart(?:igo|\.)?s?\.?\s*(\d+)\s*[.º°o]*"
    r"(?:\s*,\s*n[.º°o]*\s*\d+)?"
    r".{0,50}?"
    r"(Decreto-?Lei\s+n?[.º°o]*\s*\d{1,5}\s*/\s*\d{2,4}"
    r"|Lei\s+n?[.º°o]*\s*\d{1,5}\s*/\s*\d{2,4}"
    r"|Código\s+Civil|Código\s+Penal|\bCC\b)"
)
ORG_RE = re.compile(
    r"(?P<name>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÁÉÍÓÚÂÊÔÃÕÇ&.'’-]{2,40}"
    r"(?:[ \t]+[\wÁÉÍÓÚÂÊÔÃÕÇ&.'’-]{2,40}){0,5}"
    r"[ \t]*,?[ \t]*(?:Lda\.?|S\.A\.?|Unipessoal))"
)
OPERATIVE_RE = re.compile(r"(?i)julga-se|julgo|decide-se|absolve-se|delibera-se")
PERSONAL_RE = re.compile(r"(?i)\b(?:demandante|demandado|residente|contribuinte|nipc)\b")
OUTCOMES = (
    ("parcialmente-procedente", "parcialmente procedente", r"parcialmente\s+procedente"),
    ("parcialmente-improcedente", "parcialmente improcedente", r"parcialmente\s+improcedente"),
    ("improcedente", "improcedente", r"totalmente\s+improcedente"),
    ("procedente", "procedente", r"totalmente\s+procedente"),
    ("improcedente", "improcedente", r"\bimprocedente\b"),
    ("procedente", "procedente", r"\bprocedente\b"),
    ("absolvicao-da-instancia", "absolvição da instância", r"absolvi[cç][aã]o\s+da\s+inst[aâ]ncia"),
    ("incompetencia-material", "incompetência material", r"incompet[eê]ncia\s+material"),
)
SECTORS = (
    ("energy", "energy", r"energia\s+el[eé]trica|g[aá]s\s+natural|\beletricidade\b"),
    (
        "water-and-environmental-services",
        "water and environmental services",
        r"saneamento|res[ií]duos|[aá]gua\s+pot[aá]vel|fornecimento[^.\n]{0,40}\b[aá]gua\b",
    ),
    (
        "travel-and-transport",
        "travel and transport",
        r"\bvoo\b|transporte\s+a[eé]reo|cancelamento\s+d[eo]\s+voo|atraso\s+d[eo]\s+voo",
    ),
    (
        "communications",
        "communications",
        r"comunica[cç][oõ]es\s+eletr[oó]nicas|servi[cç]o\s+telef[oó]nico",
    ),
    (
        "financial-services",
        "financial services",
        r"\bseguros?\b|cr[eé]dito\s+ao\s+consumo|cart[aã]o\s+de\s+cr[eé]dito",
    ),
    (
        "consumer-goods",
        "consumer goods",
        r"falta\s+de\s+conformidade|garantia\s+legal|defeito\s+do\s+bem",
    ),
)
DOCTRINES = (
    ("falta-de-conformidade", "falta de conformidade", r"falta\s+de\s+conformidade"),
    ("incompetencia-material", "incompetência material", r"incompet[eê]ncia\s+material"),
    (
        "servicos-publicos-essenciais",
        "serviços públicos essenciais",
        r"servi[cç]os\s+p[uú]blicos\s+essenciais",
    ),
    ("onus-da-prova", "ónus da prova", r"[oó]nus\s+da\s+prova"),
    ("caducidade", "caducidade", r"\bcaducidade\b"),
    ("abuso-de-direito", "abuso de direito", r"abuso\s+de\s+direito"),
    ("prescricao", "prescrição", r"\bprescri[cç][aã]o\b"),
)
CODE_KEYS = {
    "código civil": ("codigo-civil", "Código Civil"),
    "código penal": ("codigo-penal", "Código Penal"),
    "código de processo civil": ("codigo-de-processo-civil", "Código de Processo Civil"),
    "código de processo penal": ("codigo-de-processo-penal", "Código de Processo Penal"),
}
CITATION_WINDOWS = ("header", "applicable_law", "citation", "disposition")
CAPTION_WINDOWS = ("header",)
ENTITY_WINDOWS = ("header", "party")
DOCTRINE_WINDOWS = ("header", "applicable_law", "citation", "disposition")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=sort_keys) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def tranche_dirs(root: Path) -> list[Path]:
    base = root / "data" / "enrichment" / "tranches"
    if not base.is_dir():
        return []
    found = [path for path in base.iterdir() if path.is_dir() and TRANCHE_RE.match(path.name)]
    return sorted(found, key=lambda path: path.name)


def _ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [str(row["id"]) for row in graph.load_jsonl(path) if row.get("id")]


def claimed_ids(root: Path, skip_tranche: str | None = None) -> set[str]:
    claimed = set(_ids(root / "data" / "enrichment" / "pilot-manifest.jsonl"))
    for path in tranche_dirs(root):
        if path.name == skip_tranche:
            continue
        claimed.update(_ids(path / "manifest.jsonl"))
    return claimed


def load_catalog(root: Path) -> list[dict[str, Any]]:
    return graph.load_jsonl(root / "data" / "catalog.jsonl")


def next_unclaimed(
    records: list[dict[str, Any]], claimed: set[str], seed: int, size: int
) -> list[dict[str, Any]]:
    if size < 1:
        raise SystemExit("size must be at least 1")
    remaining = [row for row in records if str(row.get("id")) not in claimed]
    remaining.sort(key=lambda row: (select_pilot.tie(seed, row), str(row["id"])))
    if len(remaining) < size:
        raise SystemExit(
            f"only {len(remaining)} catalog documents remain outside the pilot and tranches; "
            f"refusing to select {size}"
        )
    return remaining[:size]


def select_tranche(root: Path, size: int, seed: int) -> dict[str, Any]:
    root = root.resolve()
    records = load_catalog(root)
    dirs = tranche_dirs(root)
    target: str | None = None
    if dirs:
        last = dirs[-1]
        sealed = any(last.glob("extractor-*.jsonl"))
        meta = read_json(last / "tranche.json")
        if not sealed and meta.get("seed") == seed and meta.get("size") == size:
            target = last.name
    if target is None:
        number = 1 if not dirs else int(TRANCHE_RE.match(dirs[-1].name).group(1)) + 1
        target = f"t{number:03d}"
        skip = None
    else:
        skip = target
    chosen = next_unclaimed(records, claimed_ids(root, skip), seed, size)
    destination = root / "data" / "enrichment" / "tranches" / target
    destination.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    ids: list[str] = []
    for rank, record in enumerate(chosen):
        copy = dict(record)
        copy["selection_reasons"] = [f"tranche-queue:{target}:seed={seed}:rank={rank}"]
        item = select_pilot.manifest_record(root, copy)
        item["tranche"] = target
        item["tranche_seed"] = seed
        item["tranche_rank"] = rank
        manifest_rows.append(item)
        ids.append(str(record["id"]))
    write_jsonl(destination / "manifest.jsonl", manifest_rows)
    meta = {"tranche": target, "size": size, "seed": seed, "batch_size": BATCH_SIZE, "document_ids": ids}
    (destination / "tranche.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"tranche": target, "selected": len(ids), "output": str(destination / "manifest.jsonl")}


def _catalog_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in rows}


def write_packets(root: Path, tranche: str | None = None, batch_size: int = BATCH_SIZE) -> list[dict[str, Any]]:
    if batch_size < 1:
        raise SystemExit("batch size must be at least 1")
    root = root.resolve()
    dirs = tranche_dirs(root)
    if tranche is not None:
        dirs = [path for path in dirs if path.name == tranche]
        if not dirs:
            raise SystemExit(f"unknown tranche {tranche}")
    if not dirs:
        raise SystemExit("no tranches to packet")
    catalog = _catalog_index(load_catalog(root))
    reports = []
    for directory in dirs:
        manifest = graph.load_jsonl(directory / "manifest.jsonl")
        selected = []
        payloads: dict[str, str] = {}
        signal_rows: dict[str, dict[str, Any]] = {}
        for item in manifest:
            doc_id = str(item["id"])
            if doc_id not in catalog:
                raise SystemExit(f"{directory.name}: {doc_id} is not in data/catalog.jsonl")
            record = catalog[doc_id]
            payload = signals.parse_full_text((root / record["rel_raw"]).read_text(encoding="utf-8"))
            payloads[doc_id] = payload
            signal_rows[doc_id] = signals.extract_signals(payload, record)
            selected.append(record)
        neighbors = signals.lexical_neighbors(selected, payloads)
        packets = [
            signals.build_packet(
                record,
                payloads[str(record["id"])],
                signal_rows[str(record["id"])],
                neighbors[str(record["id"])],
            )
            for record in selected
        ]
        write_jsonl(directory / "packets.jsonl", packets, sort_keys=True)
        batches = []
        for index, start in enumerate(range(0, len(packets), batch_size), 1):
            chunk = packets[start : start + batch_size]
            name = f"{index:02d}"
            write_jsonl(directory / f"packets-{name}.jsonl", chunk, sort_keys=True)
            batches.append({"batch": name, "document_ids": [row["id"] for row in chunk]})
        batch_meta = {"tranche": directory.name, "batch_size": batch_size, "batches": batches}
        (directory / "batches.json").write_text(
            json.dumps(batch_meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        reports.append({"tranche": directory.name, "packets": len(packets), "batches": len(batches)})
    return reports


def status_report(root: Path) -> dict[str, Any]:
    root = root.resolve()
    catalog_ids = {str(row["id"]) for row in load_catalog(root)}
    pilot_ids = set(_ids(root / "data" / "enrichment" / "pilot-manifest.jsonl")) & catalog_ids
    processed = set(pilot_ids)
    tranches = []
    for directory in tranche_dirs(root):
        manifest_ids = _ids(directory / "manifest.jsonl")
        extracted: list[str] = []
        for path in sorted(directory.glob("extractor-*.jsonl")):
            for row in graph.load_jsonl(path):
                doc_id = str(row.get("document_id") or "")
                if doc_id in catalog_ids:
                    extracted.append(doc_id)
        extracted_ids = set(extracted)
        processed.update(extracted_ids)
        tranches.append({
            "tranche": directory.name,
            "manifest": len(manifest_ids),
            "extracted": len(extracted_ids),
            "reviewers": (directory / "reviewer-1.jsonl").is_file()
            and (directory / "reviewer-2.jsonl").is_file(),
        })
    csv_count = len(catalog_ids)
    return {
        "csv_catalog": csv_count,
        "pilot": len(pilot_ids),
        "processed": len(processed),
        "remaining": csv_count - len(processed),
        "tranches": tranches,
    }


def _windows(packet: dict[str, Any], names: Iterable[str]) -> list[dict[str, Any]]:
    found = []
    stored = packet.get("windows") or {}
    for name in names:
        for window in stored.get(name) or []:
            if not isinstance(window, dict):
                continue
            start, end, quote = window.get("start"), window.get("end"), window.get("quote")
            if isinstance(start, int) and isinstance(end, int) and isinstance(quote, str):
                found.append({
                    "name": name,
                    "section": WINDOW_SECTION[name],
                    "start": start,
                    "end": end,
                    "quote": quote,
                })
    return found


def _inside_window(start: int, end: int, packet: dict[str, Any]) -> bool:
    for name in WINDOW_SECTION:
        for window in _windows(packet, (name,)):
            if window["start"] <= start and end <= window["end"]:
                return True
    return False


def check_tranche(root: Path, tranche: str) -> dict[str, Any]:
    root = root.resolve()
    directory = root / "data" / "enrichment" / "tranches" / tranche
    errors: list[str] = []
    if not (directory / "manifest.jsonl").is_file():
        return {"ok": False, "tranche": tranche, "errors": ["missing manifest"]}
    manifest_ids = _ids(directory / "manifest.jsonl")
    packets = {
        str(row["id"]): row
        for row in graph.load_jsonl(directory / "packets.jsonl")
    } if (directory / "packets.jsonl").is_file() else {}
    catalog, _ = graph.load_catalog(root / "data" / "catalog.jsonl")
    batch_counts: dict[str, dict[str, int]] = {}
    predicates: Counter[str] = Counter()
    seen_ids: list[str] = []
    raw_spans = 0
    for path in sorted(directory.glob("extractor-*.jsonl")):
        batch = path.stem.split("-")[-1]
        docs = assertions = 0
        packet_list = directory / f"packets-{batch}.jsonl"
        if packet_list.is_file():
            expected = [str(row["id"]) for row in graph.load_jsonl(packet_list)]
        else:
            expected = None
        actual_ids = []
        for row in graph.load_jsonl(path):
            docs += 1
            doc_id = str(row.get("document_id") or "")
            actual_ids.append(doc_id)
            seen_ids.append(doc_id)
            packet = packets.get(doc_id)
            if packet is None:
                errors.append(f"{doc_id}: extractor row has no packet")
            laterals = 0
            for assertion in row.get("assertions") or []:
                assertions += 1
                predicates[str(assertion.get("predicate"))] += 1
                if assertion.get("predicate") in graph.LATERAL_PREDICATES:
                    laterals += 1
                try:
                    graph.validate_assertion_shape(assertion)
                    expected_id = graph.compute_assertion_id(assertion)
                    if assertion.get("assertion_id") != expected_id:
                        errors.append(f"{doc_id}: assertion id mismatch")
                    graph.validate_provenance(assertion, root, catalog)
                except (graph.ContractError, KeyError, TypeError, OSError) as exc:
                    errors.append(f"{doc_id}: {exc}")
                    continue
                provenance = assertion.get("provenance") or {}
                if provenance.get("kind") == "raw-span":
                    raw_spans += 1
                    start, end = provenance.get("start"), provenance.get("end")
                    if packet is not None and not _inside_window(start, end, packet):
                        errors.append(
                            f"{doc_id}: raw span {start}:{end} is outside packet windows"
                        )
            if laterals > 3:
                errors.append(f"{doc_id}: {laterals} source-to-source links exceeds 3")
        if expected is not None and actual_ids != expected:
            errors.append(f"{path.name}: document ids do not match {packet_list.name}")
        batch_counts[batch] = {"documents": docs, "assertions": assertions}
    if seen_ids != manifest_ids:
        errors.append("extractor coverage does not match manifest order")
    if len(seen_ids) != len(set(seen_ids)):
        errors.append("duplicate extractor document ids")
    return {
        "ok": not errors,
        "tranche": tranche,
        "documents": len(seen_ids),
        "assertions": sum(item["assertions"] for item in batch_counts.values()),
        "raw_spans_checked": raw_spans,
        "batches": batch_counts,
        "predicates": dict(sorted(predicates.items())),
        "errors": errors[:50],
        "error_count": len(errors),
    }


def extraction_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    pilot = root / "data" / "enrichment" / "pilot"
    if pilot.is_dir():
        paths.extend(sorted(pilot.glob("extractor-*.jsonl")))
    for directory in tranche_dirs(root):
        paths.extend(sorted(directory.glob("extractor-*.jsonl")))
    return paths


def merged_reviewers(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pilot = root / "data" / "enrichment" / "pilot"
    left_path, right_path = pilot / "reviewer-1.jsonl", pilot / "reviewer-2.jsonl"
    if not left_path.is_file() or not right_path.is_file():
        raise graph.ContractError("pilot reviewer-1.jsonl and reviewer-2.jsonl are required")
    left, right = graph.load_jsonl(left_path), graph.load_jsonl(right_path)
    for directory in tranche_dirs(root):
        first, second = directory / "reviewer-1.jsonl", directory / "reviewer-2.jsonl"
        if first.is_file() ^ second.is_file():
            raise graph.ContractError(f"{directory.name} must have both reviewer files or neither")
        if first.is_file():
            left.extend(graph.load_jsonl(first))
            right.extend(graph.load_jsonl(second))
    return left, right


def build_all(root: Path, dry_run: bool = False, output_root: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    paths = extraction_paths(root)
    if not paths:
        raise graph.ContractError("no extractor JSONL files found")
    left, right = merged_reviewers(root)
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        left_path, right_path = folder / "reviewer-1.jsonl", folder / "reviewer-2.jsonl"
        write_jsonl(left_path, left)
        write_jsonl(right_path, right)
        report = graph.build_graph(root, paths, [left_path, right_path], output_root, dry_run)
    report["extraction_files"] = [path.relative_to(root).as_posix() for path in paths]
    report["dry_run"] = dry_run
    return report


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text)


def _subject(record: dict[str, Any]) -> dict[str, str]:
    return {
        "key": f"document:{record['id']}",
        "type": "document",
        "label": str(record.get("filename") or record["id"]),
        "path": str(record["rel_source"]).replace("\\", "/"),
    }


def _object(key: str, node_type: str, label: str, path: str | None = None) -> dict[str, str]:
    node = {"key": key, "type": node_type, "label": label}
    resolved = path or graph.canonical_node_path(node)
    if resolved:
        node["path"] = resolved
    return node


def _finish(assertion: dict[str, Any]) -> dict[str, Any]:
    assertion["assertion_id"] = graph.compute_assertion_id(assertion)
    return assertion


def _raw(
    record: dict[str, Any],
    predicate: str,
    node: dict[str, str],
    payload: str,
    start: int,
    end: int,
    section: str,
    reason: str,
    confidence: float,
) -> dict[str, Any] | None:
    if not (0 <= start < end <= len(payload)) or end - start > 450:
        return None
    quote = payload[start:end]
    if not quote.strip():
        return None
    assertion = {
        "subject": _subject(record),
        "predicate": predicate,
        "object": node,
        "source_document_id": record["id"],
        "provenance": {
            "kind": "raw-span",
            "raw_path": str(record["rel_raw"]).replace("\\", "/"),
            "section": section,
            "start": start,
            "end": end,
            "quote": quote,
            "evidence_hash": graph.sha256_text(quote),
        },
        "method": "grok-4.6",
        "extractor_version": EXTRACTOR_VERSION,
        "confidence": confidence,
        "review_status": "candidate",
        "reason": reason,
    }
    return _finish(assertion)


def _metadata(
    record: dict[str, Any], predicate: str, node: dict[str, str], field: str, value: Any, reason: str
) -> dict[str, Any]:
    assertion = {
        "subject": _subject(record),
        "predicate": predicate,
        "object": node,
        "source_document_id": record["id"],
        "provenance": {
            "kind": "metadata-field",
            "field": field,
            "value": value,
            "evidence_hash": graph.sha256_text(value),
        },
        "method": "metadata",
        "extractor_version": EXTRACTOR_VERSION,
        "confidence": 1.0,
        "review_status": "candidate",
        "reason": reason,
    }
    return _finish(assertion)


def _spans(window: dict[str, Any], pattern: re.Pattern[str]) -> list[tuple[int, int, re.Match[str]]]:
    found = []
    for match in pattern.finditer(window["quote"]):
        found.append((window["start"] + match.start(), window["start"] + match.end(), match))
    return found


def _smallest_cover(groups: list[list[tuple[int, int]]], limit: int) -> tuple[int, int] | None:
    best: tuple[int, int, int] | None = None

    def walk(index: int, chosen: list[tuple[int, int]]) -> None:
        nonlocal best
        if index == len(groups):
            start = min(span[0] for span in chosen)
            end = max(span[1] for span in chosen)
            gap = end - start
            if gap <= limit and (best is None or gap < best[0]):
                best = (gap, start, end)
            return
        for span in groups[index]:
            walk(index + 1, chosen + [span])

    if not groups or any(not group for group in groups):
        return None
    walk(0, [])
    if best is None:
        return None
    return best[1], best[2]


def _pull_decreto(payload: str, window_start: int, token_start: int) -> int | None:
    """Return a start offset that includes a broken Decreto/Dec. prefix, if close."""

    head = payload[window_start:token_start]
    prefix = DECRETO_PREFIX_RE.search(head)
    if prefix and token_start - (window_start + prefix.start()) <= 20:
        return window_start + prefix.start()
    return None


def _law_key(kind: str, number: str, eu: bool = False) -> tuple[str, str]:
    normalized = re.sub(r"\s+", "", number)
    token = "decreto-lei" if kind.casefold().startswith("decreto") else kind.casefold()
    juris = "eu" if eu else "pt"
    label_kind = "Decreto-Lei" if token == "decreto-lei" else kind[:1].upper() + kind[1:]
    if token == "lei":
        label_kind = "Lei"
    elif token == "portaria":
        label_kind = "Portaria"
    elif token == "regulamento":
        label_kind = "Regulamento"
    return f"instrument:{juris}:{token}:{normalized}", f"{label_kind} n.º {normalized}"


def _code_key(text: str) -> tuple[str, str] | None:
    found = CODE_KEYS.get(re.sub(r"\s+", " ", text).strip().casefold())
    if not found:
        return None
    return f"instrument:pt:{found[0]}", found[1]


def _classify(payload: str, website: str) -> str:
    head = payload[:1200].casefold()
    if "revista" in head[:800] or "issn" in head[:800]:
        return "legal-commentary"
    arbitral = website in ARBITRATION_SITES or "arbitral" in head or "tribunal" in head
    if arbitral and any(token in head for token in ("sentença", "sentenca", "decisão", "decisao", "processo", "reclam")):
        return "arbitral-decision"
    if "parecer" in head[:600]:
        return "administrative-document"
    return "unknown"


def _outcome_match(text: str, base: int, require_operative: bool) -> tuple[int, int, str, str] | None:
    operative = [(match.start(), match.end()) for match in OPERATIVE_RE.finditer(text)]
    found: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for key, label, pattern in OUTCOMES:
        for match in re.finditer(pattern, text, re.I):
            if any(not (match.end() <= start or match.start() >= end) for start, end in occupied):
                continue
            if require_operative and not any(0 <= match.start() - op_end <= 80 for _, op_end in operative):
                continue
            occupied.append((match.start(), match.end()))
            found.append((base + match.start(), base + match.end(), key, label))
    if not found:
        return None
    return max(found, key=lambda item: item[0])


def _named_organization(name: str) -> bool:
    if re.search(r"---|[*]{2,}|_{3,}", name):
        return False
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÂÊÔÃÕÇ]{4,}", name)
    stop = {
        "reclamante", "reclamada", "requerente", "requerida", "consumidor",
        "fornecedor", "unipessoal", "sociedade",
    }
    return any(_fold(token) not in stop for token in tokens)


def draft_document_row(
    record: dict[str, Any],
    payload: str,
    packet: dict[str, Any],
    peers: list[dict[str, Any]],
    batch: str,
) -> dict[str, Any]:
    """Draft one extractor row from packet windows only.

    Catalog website/topic become metadata edges, matching the pilot. Every
    other claim is a slice of a packet window. CSV summary text is never read.
    """

    assertions: list[dict[str, Any]] = []
    website = record.get("website")
    topic = record.get("topic")
    if isinstance(website, str) and website.strip():
        slug = str(record.get("website_slug") or graph.slugify(website))
        assertions.append(_metadata(
            record,
            "published_by",
            _object(f"organization:{slug}", "organization", website),
            "website",
            website,
            "Catalog website identifies the importing source organization.",
        ))
    if isinstance(topic, str) and topic.strip():
        slug = str(record.get("topic_slug") or graph.slugify(topic))
        assertions.append(_metadata(
            record,
            "about_topic",
            _object(f"topic:{slug}", "topic", topic),
            "topic",
            topic,
            "Catalog topic field copied as filing metadata; not a holding.",
        ))

    header_windows = _windows(packet, CAPTION_WINDOWS)
    forum_key = None
    case_key = None
    process_number = None
    if header_windows:
        header = header_windows[0]
        forum_spans: list[tuple[str, str, list[tuple[int, int]]]] = []
        for slug, label, pattern in FORUMS:
            spans = [(start, end) for start, end, _ in _spans(header, pattern)]
            if spans:
                forum_spans.append((slug, label, spans))
        preferred = str(record.get("website_slug") or "")
        forum_spans.sort(key=lambda item: (item[0] != preferred, item[2][0][0]))
        adjudicative = [(start, end) for start, end, _ in _spans(header, ADJUDICATIVE_RE)]
        processes = _spans(header, PROCESS_RE)
        if processes:
            process_number = re.sub(r"\s+", "", processes[0][2].group("num"))
        if forum_spans and adjudicative:
            slug, label, spans = forum_spans[0]
            cover = _smallest_cover([spans, adjudicative], 90)
            quote = payload[cover[0] : cover[1]] if cover else ""
            if cover and slug in _fold(quote) and not PERSONAL_RE.search(quote):
                forum_key = f"forum:pt:{slug}"
                made = _raw(
                    record,
                    "decided_by",
                    _object(forum_key, "forum", label),
                    payload,
                    cover[0],
                    cover[1],
                    "header",
                    f"Header names {label} in an adjudicative context.",
                    0.96 if cover[1] - cover[0] <= 180 else 0.93,
                )
                if made:
                    assertions.append(made)
        if forum_key and process_number and processes and adjudicative:
            slug = forum_key.removeprefix("forum:pt:")
            spans = next(item[2] for item in forum_spans if item[0] == slug)
            process_spans = [(start, end) for start, end, _ in processes]
            cover = _smallest_cover([process_spans, spans, adjudicative], 160)
            quote = payload[cover[0] : cover[1]] if cover else ""
            folded = _fold(quote)
            if (
                cover
                and not PERSONAL_RE.search(quote)
                and slug in folded
                and _fold(process_number) in folded
                and any(token in folded for token in ("tribunal", "arbitragem", "julgadodepaz"))
            ):
                case_key = f"case:pt:{slug}:{process_number}"
                made = _raw(
                    record,
                    "document_of",
                    _object(case_key, "case", f"Processo {process_number}"),
                    payload,
                    cover[0],
                    cover[1],
                    "header",
                    f"Header states process {process_number} together with the {slug} forum.",
                    0.95 if cover[1] - cover[0] <= 240 else 0.91,
                )
                if made:
                    assertions.append(made)

    outcome_status = None
    disposition = _windows(packet, ("disposition",))
    outcome = None
    for window in disposition:
        outcome = _outcome_match(window["quote"], window["start"], require_operative=False)
        if outcome:
            break
    if outcome is None:
        for window in header_windows:
            outcome = _outcome_match(window["quote"], window["start"], require_operative=True)
            if outcome:
                break
    if outcome is not None:
        start, end, key, label = outcome
        outcome_status = key
        made = _raw(
            record,
            "has_outcome",
            _object(f"outcome:{key}", "outcome", label),
            payload,
            start,
            end,
            "disposition" if disposition and any(
                window["start"] <= start and end <= window["end"] for window in disposition
            ) else "header",
            "Disposition language states this outcome.",
            0.95,
        )
        if made:
            assertions.append(made)

    instruments: dict[str, dict[str, Any]] = {}
    provisions: dict[str, dict[str, Any]] = {}
    for window in _windows(packet, CITATION_WINDOWS):
        for start, end, match in _spans(window, LAW_RE):
            kind = match.group(1)
            # Line-broken "Decreto- / Lei n.º 84/2021" and "Dec. Lei" otherwise
            # key as an ordinary lei. Pull the prefix into the quote when it
            # still sits in this window.
            if kind.casefold() == "lei":
                pulled = _pull_decreto(payload, window["start"], start)
                if pulled is not None:
                    start = pulled
                    kind = "Decreto-Lei"
            key, _label = _law_key(kind, match.group(2))
            instruments.setdefault(key, {
                "start": start, "end": end, "section": window["section"], "label": payload[start:end],
            })
        for start, end, match in _spans(window, REG_RE):
            eu = bool(match.group(1))
            key, _label = _law_key("Regulamento", match.group(2), eu)
            instruments.setdefault(key, {"start": start, "end": end, "section": window["section"], "label": payload[start:end]})
        for start, end, match in _spans(window, CODE_RE):
            identified = _code_key(match.group(1))
            if identified:
                key, label = identified
                instruments.setdefault(key, {"start": start, "end": end, "section": window["section"], "label": label})
        for start, end, match in _spans(window, ART_RE):
            number = match.group(1)
            instrument_text = match.group(2)
            if re.fullmatch(r"CC", instrument_text, re.I):
                inst_key, inst_label = "instrument:pt:codigo-civil", "Código Civil"
            elif instrument_text.casefold().startswith("código"):
                identified = _code_key(instrument_text)
                if not identified:
                    continue
                inst_key, inst_label = identified
            else:
                law = LAW_RE.search(instrument_text)
                if not law:
                    continue
                kind = law.group(1)
                if kind.casefold() == "lei":
                    token_start = window["start"] + match.start(2)
                    pulled = _pull_decreto(payload, window["start"], token_start)
                    if pulled is not None:
                        kind = "Decreto-Lei"
                        if pulled < start:
                            start = pulled
                inst_key, inst_label = _law_key(kind, law.group(2))
            suffix = inst_key.removeprefix("instrument:")
            prov_key = f"provision:{suffix}:art.{number}"
            provisions.setdefault(prov_key, {
                "start": start,
                "end": end,
                "section": window["section"],
                "label": f"art. {number} {inst_label}",
            })
    for key, item in list(instruments.items())[:4]:
        made = _raw(
            record, "cites_instrument", _object(key, "instrument", re.sub(r"\s+", " ", item["label"]).strip()),
            payload, item["start"], item["end"], item["section"],
            "Window quotes this instrument.", 0.96,
        )
        if made:
            assertions.append(made)
    for key, item in list(provisions.items())[:3]:
        made = _raw(
            record, "cites_provision", _object(key, "provision", item["label"]),
            payload, item["start"], item["end"], item["section"],
            "Window quotes this provision.", 0.94,
        )
        if made:
            assertions.append(made)

    for slug, label, pattern in SECTORS:
        placed = False
        for window in _windows(packet, ENTITY_WINDOWS):
            spans = _spans(window, re.compile(pattern, re.I))
            if not spans:
                continue
            start, end, _match = spans[0]
            made = _raw(
                record, "about_sector", _object(f"sector:{slug}", "sector", label),
                payload, start, end, window["section"],
                f"Window text places the dispute in {label}.", 0.92,
            )
            if made:
                assertions.append(made)
                placed = True
                break
        if placed:
            break

    doctrine_count = 0
    for slug, label, pattern in DOCTRINES:
        if doctrine_count >= 2:
            break
        for window in _windows(packet, DOCTRINE_WINDOWS):
            spans = _spans(window, re.compile(pattern, re.I))
            if not spans:
                continue
            start, end, _match = spans[0]
            made = _raw(
                record, "about_doctrine", _object(f"doctrine:{slug}", "doctrine", label),
                payload, start, end, window["section"],
                f"Window states the doctrine {label}.", 0.92,
            )
            if made:
                assertions.append(made)
                doctrine_count += 1
                break

    mention_keys: set[str] = set()
    for window in _windows(packet, CAPTION_WINDOWS):
        for slug, label, pattern in FORUMS:
            spans = _spans(window, pattern)
            if not spans:
                continue
            key = f"organization:{slug}"
            if key in mention_keys:
                continue
            start, end, _match = spans[0]
            made = _raw(
                record, "mentions_entity", _object(key, "organization", label),
                payload, start, end, "header",
                f"Header names {label}.", 0.95,
            )
            if made:
                assertions.append(made)
                mention_keys.add(key)
            break
    org_count = 0
    for window in _windows(packet, ENTITY_WINDOWS):
        if org_count >= 2 or len(mention_keys) >= 3:
            break
        for start, end, match in _spans(window, ORG_RE):
            if org_count >= 2 or len(mention_keys) >= 3:
                break
            name = re.sub(r"\s+", " ", match.group("name")).strip(" ,")
            if not _named_organization(name):
                continue
            slug = graph.slugify(name)
            key = f"organization:{slug}"
            if len(slug) < 4 or key in mention_keys:
                continue
            made = _raw(
                record, "mentions_entity", _object(key, "organization", name),
                payload, start, end, window["section"],
                "Window names this organization; the party role stays case-local.",
                0.93,
            )
            if made:
                assertions.append(made)
                mention_keys.add(key)
                org_count += 1

    family_keys: list[str] = []
    content_hash = str(record.get("content_hash") or "")
    for peer in peers[:3]:
        if str(peer.get("content_hash") or "") != content_hash or not content_hash:
            continue
        assertion = {
            "subject": _subject(record),
            "predicate": "exact_duplicate_of",
            "object": _object(
                f"document:{peer['id']}",
                "document",
                str(peer.get("filename") or peer["id"]),
                str(peer["rel_source"]).replace("\\", "/"),
            ),
            "source_document_id": record["id"],
            "provenance": {
                "kind": "content-hash",
                "content_hash": content_hash,
                "peer_document_id": peer["id"],
            },
            "method": "content-hash",
            "extractor_version": EXTRACTOR_VERSION,
            "confidence": 1.0,
            "review_status": "candidate",
            "reason": f"Identical Full-text content_hash with {peer['id']}.",
        }
        assertions.append(_finish(assertion))
        family_keys.append(str(peer["id"]))

    date_value = None
    if header_windows:
        found = signals.DATE_RE.search(header_windows[0]["quote"])
        if found:
            date_value = found.group(0)
    sectors = [item["object"]["key"] for item in assertions if item["predicate"] == "about_sector"]
    doctrines = [item["object"]["key"] for item in assertions if item["predicate"] == "about_doctrine"]
    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "document_id": record["id"],
        "raw_path": str(record["rel_raw"]).replace("\\", "/"),
        "source_path": str(record["rel_source"]).replace("\\", "/"),
        "document_type": _classify(payload, str(website or "")),
        "process_number": process_number,
        "case_key": case_key,
        "forum_key": forum_key,
        "decision_date": date_value,
        "topic_raw": topic if isinstance(topic, str) else None,
        "sectors": sectors,
        "doctrines": doctrines,
        "outcome_status": outcome_status,
        "family_keys": family_keys,
        "batch": batch,
        "assertions": assertions,
    }


def write_extractor_files(root: Path, tranche: str) -> dict[str, Any]:
    root = root.resolve()
    directory = root / "data" / "enrichment" / "tranches" / tranche
    manifest = graph.load_jsonl(directory / "manifest.jsonl")
    packets = {str(row["id"]): row for row in graph.load_jsonl(directory / "packets.jsonl")}
    batch_meta = read_json(directory / "batches.json")
    batches = batch_meta.get("batches") or []
    if not batches:
        raise SystemExit(f"{tranche} has no batches.json; run packets first")
    catalog = load_catalog(root)
    by_id = _catalog_index(catalog)
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in catalog:
        if row.get("content_hash"):
            by_hash[str(row["content_hash"])].append(row)
    counts = {}
    for batch in batches:
        name = str(batch["batch"])
        batch_ids = set(batch["document_ids"])
        rows = []
        for doc_id in batch["document_ids"]:
            record = by_id[doc_id]
            payload = signals.parse_full_text((root / record["rel_raw"]).read_text(encoding="utf-8"))
            content_hash = str(record.get("content_hash") or "")
            peers = [
                peer for peer in by_hash.get(content_hash, [])
                if peer["id"] != doc_id
            ]
            peers.sort(key=lambda peer: (peer["id"] not in batch_ids, str(peer["id"])))
            rows.append(draft_document_row(record, payload, packets[doc_id], peers, name))
        write_jsonl(directory / f"extractor-{name}.jsonl", rows)
        counts[name] = {
            "documents": len(rows),
            "assertions": sum(len(row["assertions"]) for row in rows),
        }
    return {"tranche": tranche, "batches": counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)

    select = sub.add_parser("select", help="choose the next unclaimed catalog documents")
    select.add_argument("--size", type=int, required=True)
    select.add_argument("--seed", type=int, required=True)

    packets = sub.add_parser("packets", help="write packet windows for one tranche or all tranches")
    packets.add_argument("--tranche")
    packets.add_argument("--batch-size", type=int, default=BATCH_SIZE)

    sub.add_parser("status", help="print processed and remaining CSV-catalog counts")

    check = sub.add_parser("check", help="validate tranche extractor spans against raw text and packets")
    check.add_argument("tranche")

    build = sub.add_parser("build", help="adjudicate pilot plus tranche extractors and reviewers")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--output-root", type=Path)

    args = parser.parse_args(argv)
    root = args.root
    try:
        if args.command == "select":
            report: Any = select_tranche(root, args.size, args.seed)
        elif args.command == "packets":
            report = write_packets(root, args.tranche, args.batch_size)
        elif args.command == "status":
            report = status_report(root)
        elif args.command == "check":
            report = check_tranche(root, args.tranche)
        else:
            report = build_all(root, args.dry_run, args.output_root)
    except (graph.ContractError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if isinstance(report, dict) and report.get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
