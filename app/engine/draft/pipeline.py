"""Turn a case record into a reviewable decision packet.

Retrieval and packet validation are imported inside the functions that need
them, so this module loads even while those packages are still being written.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.engine.draft.llm import LLM
from app.engine.draft.prompts import (
    CANONICAL_QUERIES,
    DRAFT_SCHEMA,
    EVIDENCE_SCHEMA,
    LAW_SECTIONS,
    MATTER_SCHEMA,
    REPAIR_SCHEMA,
    RESEARCH_SCHEMA,
    SECTION_ORDER,
    STEP_DRAFT,
    STEP_EVIDENCE,
    STEP_MATTER,
    STEP_REPAIR,
    STEP_RESEARCH,
    draft_user,
    evidence_user,
    matter_user,
    repair_user,
    research_user,
    system_prompt,
)


RECORD_CHAR_LIMIT = 100_000
EXCERPT_CHAR_LIMIT = 1_500
MAX_PASSAGES = 20
SEARCH_K = 6
TWOPLACES = Decimal("0.01")
VALIDATE_MISSING = "validate_packet indisponível"

_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_ANONYMOUS = {
    "nao identificado",
    "nao identificada",
    "nao indicado",
    "nao indicada",
    "desconhecido",
    "desconhecida",
    "reclamante",
    "reclamada",
    "reclamado",
    "a reclamante",
    "a reclamada",
    "o reclamante",
    "o reclamado",
    "n/a",
    "na",
    "none",
    "null",
}
_SLUG_STOP = {
    "n",
    "no",
    "nr",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "e",
    "o",
    "a",
    "os",
    "as",
    "em",
    "para",
}
_PROVED_BASES = {"common", "admission", "procedural_record"}
_NOT_PROVED_BASES = {"unilateral_assertion", "unseen_attachment"}
_FACT_SECTIONS = {"factos_provados", "factos_nao_provados"}
_NARRATIVE = {"relatorio", "objeto_litigio", "saneador", "decisao"}
_URL_RE = re.compile(r"(?i)\b(?:https?://|file://)\S+")
_QUOTE_RE = re.compile(r"«([^»]+)»|“([^”]+)”|\"([^\"\n]+)\"")
_PIN_RE = re.compile(
    r"linhas?\s+(\d+)\s*[\u2013\u2014\-]\s*(\d+)|linha\s+(\d+)",
    re.IGNORECASE,
)
_LETTER_PREFIX = re.compile(r"^[a-z]{1,2}\)\s*")
_NUMBER_PREFIX = re.compile(r"^\d+\.\s*")
_SUMARIO_PADS = (
    "O número do processo não é afirmado para além do que o caso indica.",
    "Não se completa a identidade das partes quando o registo as omite.",
    "A competência e a data da audiência, se omissas, ficam por estabelecer.",
    "Não se inventam distâncias, pagamentos ou assinatura.",
    "O projeto é minuta não assinada e cada parágrafo carece de revisão.",
)
_FILLERS = {
    "relatorio": (
        "O relatório limita-se ao pedido, às alterações e à sequência que o "
        "registo descreve, sem suprir omissões."
    ),
    "objeto_litigio": (
        "O objeto do litígio é o pedido deduzido no registo, na medida em que "
        "esteja quantificado e individualizado."
    ),
    "saneador": (
        "Não se afirma competência, data de audiência ou número de processo "
        "que o registo não estabeleça."
    ),
    "motivacao": (
        "A motivação distingue admissão, registo processual e alegação "
        "unilateral; o que só uma parte afirma permanece não provado."
    ),
    "fundamentacao_direito": (
        "As consequências jurídicas extraem-se somente dos excertos locais "
        "admitidos, incluindo o sentido que lhes seja contrário."
    ),
    "decisao": "A decisão quantifica apenas os pedidos constantes dos montantes.",
}


@dataclass
class _Flags:
    repaired: bool = False
    quote_failed: set[tuple[str, int]] = field(default_factory=set)
    source_stripped: set[tuple[str, int]] = field(default_factory=set)
    evidence_stripped: set[tuple[str, int]] = field(default_factory=set)


def draft_case(
    record_text: str,
    *,
    llm: LLM,
    retriever: Any,
    case_meta: dict[str, Any],
    input_record: dict[str, Any] | None = None,
    max_repairs: int = 2,
) -> dict[str, Any]:
    """Draft a decision packet and the paragraph list a judge reviews.

    Returns ``packet``, ``paragraphs``, ``errors`` and ``audit``. ``errors``
    is empty only when ``validate_packet`` accepts the packet.
    """

    record = _bounded_record(record_text)
    repairs_budget = max(0, int(max_repairs))
    prompt_parts: list[str] = []

    def ask(user: str, schema: dict[str, Any]) -> dict[str, Any]:
        system = system_prompt()
        prompt_parts.append(system)
        prompt_parts.append(user)
        raw = llm.complete_json(system, user, schema)
        if not isinstance(raw, dict):
            raise TypeError("complete_json deve devolver um objeto JSON.")
        return raw

    matter = ask(matter_user(record), MATTER_SCHEMA)
    evidence_raw = ask(evidence_user(record, matter), EVIDENCE_SCHEMA)
    research = ask(research_user(matter), RESEARCH_SCHEMA)
    queries = assemble_queries(research.get("queries"), matter)
    passages = _retrieve_passages(retriever, queries)
    prepared = prepare_sources(passages, _safe_catalog(retriever), retriever)
    drafted = ask(
        draft_user(
            record,
            matter,
            evidence_raw.get("evidence_matrix"),
            prepared,
        ),
        DRAFT_SCHEMA,
    )
    evidence = evidence_raw.get("evidence_matrix")
    sections = drafted.get("sections")
    amounts = drafted.get("amounts")
    frame = _case_frame(case_meta, matter)
    packet, flags = _finalize(
        sections,
        evidence,
        amounts,
        prepared,
        frame,
        input_record,
        retriever,
    )
    errors = _call_validate(packet, retriever)
    repairs_done = 0
    while errors and repairs_done < repairs_budget:
        repaired = ask(repair_user(packet, errors, prepared), REPAIR_SCHEMA)
        sections, evidence, amounts = _apply_repair(
            sections, evidence, amounts, repaired
        )
        packet, flags = _finalize(
            sections,
            evidence,
            amounts,
            prepared,
            frame,
            input_record,
            retriever,
        )
        repairs_done += 1
        errors = _call_validate(packet, retriever)
    flags.repaired = repairs_done > 0
    if errors is None:
        public_errors = [VALIDATE_MISSING]
    else:
        public_errors = list(errors)
    usage = getattr(llm, "usage", {}) or {}
    return {
        "packet": packet,
        "paragraphs": _build_paragraphs(packet, flags),
        "errors": public_errors,
        "audit": {
            "modelId": str(getattr(llm, "model_id", "") or ""),
            "promptSha256": hashlib.sha256(
                "\n\n".join(prompt_parts).encode("utf-8")
            ).hexdigest(),
            "inputTokens": int(usage.get("inputTokens") or 0),
            "outputTokens": int(usage.get("outputTokens") or 0),
            "sourceIds": [source["id"] for source in packet.get("sources") or []],
        },
    }


def assemble_queries(model_queries: Any, matter: Any) -> list[str]:
    """Six corpus queries plus up to two case-specific ones, capped at eight."""

    specific: list[str] = []
    flight = matter.get("flight") if isinstance(matter, dict) else None
    if isinstance(flight, dict):
        bits = [
            flight.get(key)
            for key in ("number", "origin", "destination", "date")
            if isinstance(flight.get(key), str) and flight.get(key).strip()
        ]
        if bits:
            specific.append("compensação aérea " + " ".join(str(bit).strip() for bit in bits))
    issues = matter.get("issues") if isinstance(matter, dict) else None
    if isinstance(issues, list):
        specific.extend(
            " ".join(issue.split())
            for issue in issues
            if isinstance(issue, str) and issue.strip()
        )
    if isinstance(model_queries, list):
        specific.extend(
            " ".join(query.split())
            for query in model_queries
            if isinstance(query, str) and query.strip()
        )
    return _unique(list(CANONICAL_QUERIES) + _unique(specific)[:2])[:8]


def prepare_sources(
    passages: list[dict[str, Any]],
    catalog: dict[str, Any],
    retriever: Any,
) -> list[dict[str, Any]]:
    """Group passages into citable sources. Ids are short title slugs."""

    grouped: list[dict[str, Any]] = []
    index_by_doc: dict[str, int] = {}
    used_ids: set[str] = set()
    for passage in passages:
        if not isinstance(passage, dict):
            continue
        document_id = passage.get("document_id")
        if not isinstance(document_id, str) or not document_id.strip():
            continue
        document_id = document_id.strip()
        entry = catalog.get(document_id)
        entry = entry if isinstance(entry, dict) else {}
        path = entry.get("path") or entry.get("repository_path") or passage.get("path")
        title = entry.get("title") or passage.get("title") or document_id
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(title, str) or not title.strip():
            title = document_id
        try:
            start = int(passage.get("line_start"))
            end = int(passage.get("line_end"))
        except (TypeError, ValueError):
            continue
        if end < start:
            start, end = end, start
        start = max(1, start)
        excerpt = _excerpt_text(retriever, document_id, start, end, passage.get("text"))
        if document_id not in index_by_doc:
            source_id = _source_id(title, document_id, used_ids)
            index_by_doc[document_id] = len(grouped)
            grouped.append(
                {
                    "id": source_id,
                    "title": title.strip(),
                    "path": path.strip(),
                    "document_id": document_id,
                    "ranges": [(start, end)],
                    "excerpts": [
                        {"pinpoint": _pinpoint(start, end), "text": excerpt}
                    ],
                }
            )
        else:
            source = grouped[index_by_doc[document_id]]
            source["ranges"].append((start, end))
            source["excerpts"].append(
                {"pinpoint": _pinpoint(start, end), "text": excerpt}
            )
    for source in grouped:
        source["pinpoints"] = [
            _pinpoint(start, end) for start, end in _merge_ranges(source["ranges"])
        ]
    return grouped


def _finalize(
    sections: Any,
    evidence: Any,
    amounts: Any,
    prepared: list[dict[str, Any]],
    frame: dict[str, str],
    input_record: dict[str, Any] | None,
    retriever: Any,
) -> tuple[dict[str, Any], _Flags]:
    flags = _Flags()
    matrix = _normalize_evidence(evidence)
    body = _coerce_sections(sections)
    allowed = {source["id"]: source for source in prepared}
    _ensure_minimums(body, matrix, list(allowed))
    _clean_citations(body, matrix, allowed, flags)
    _apply_prefixes(body)
    money_rows, case_value, decision_total = _normalize_amounts(amounts)
    packet: dict[str, Any] = {
        "metadata": {
            "process_number": frame["process_number"],
            "claimant": frame["claimant"],
            "respondent": frame["respondent"],
            "case_value": case_value,
            "place_and_date": frame["place_and_date"],
            "draft_date": frame["draft_date"],
            "document_title": frame["document_title"],
        },
        "policy": {
            "strict_evidence": True,
            "required_metadata": {"process_number": frame["process_number"]},
        },
        "sources": [_public_source(source) for source in prepared],
        "evidence_matrix": matrix,
        "sections": body,
        "amounts": money_rows,
        "decision_total": decision_total,
    }
    if input_record is not None:
        packet["input_record"] = copy.deepcopy(input_record)
    _scrub_strings(packet)
    _apply_quotes(body, allowed, retriever, flags)
    _ensure_decision_tail(
        body, decision_total, case_value, frame["place_and_date"]
    )
    return packet, flags


def _build_paragraphs(packet: dict[str, Any], flags: _Flags) -> list[dict[str, Any]]:
    sections = packet.get("sections") or {}
    statuses = {
        item["id"]: item["status"]
        for item in packet.get("evidence_matrix") or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    paragraphs: list[dict[str, Any]] = []
    for section in SECTION_ORDER:
        for index, spec in enumerate(sections.get(section) or []):
            if not isinstance(spec, dict):
                continue
            level, note = _confidence(section, index, spec, statuses, flags)
            paragraphs.append(
                {
                    "id": f"{section}-{index}",
                    "section": section,
                    "index": index,
                    "text": spec.get("text") or "",
                    "sourceIds": list(spec.get("source_ids") or []),
                    "evidenceIds": list(spec.get("evidence_ids") or []),
                    "confidence": level,
                    "note": note,
                }
            )
    return paragraphs


def _confidence(
    section: str,
    index: int,
    spec: dict[str, Any],
    statuses: dict[str, str],
    flags: _Flags,
) -> tuple[str, str]:
    notes: list[str] = []
    level = "high"

    def down(new: str, note: str) -> None:
        nonlocal level
        rank = {"high": 0, "medium": 1, "low": 2}
        if rank[new] > rank[level]:
            level = new
        notes.append(note)

    if flags.repaired:
        down("low", "Reparação automática; rever com cuidado.")
    if (section, index) in flags.quote_failed:
        down("low", "Citação não verificada; aspas removidas.")
    if (section, index) in flags.source_stripped:
        down("low", "Fonte alheia aos excertos foi removida.")
    if (section, index) in flags.evidence_stripped:
        down("low", "Elemento de prova incompatível foi retirado.")
    evidence_ids = list(spec.get("evidence_ids") or [])
    if section == "factos_nao_provados" or any(
        statuses.get(item) == "not_proved" for item in evidence_ids
    ):
        down("low", "Assenta em facto não provado.")
    if section in LAW_SECTIONS and not spec.get("source_ids"):
        down("low", "Proposição jurídica sem fonte local.")
    if section in _FACT_SECTIONS and not evidence_ids:
        down("low", "Facto sem elemento de prova compatível.")
    if level == "high" and section in _NARRATIVE:
        level = "medium"
        notes.append("Síntese a confirmar parágrafo a parágrafo.")
    if not notes:
        notes.append("Fundado no registo e nas fontes locais.")
    return level, " ".join(notes)


def _call_validate(packet: dict[str, Any], retriever: Any) -> list[str] | None:
    try:
        from app.engine.validate import validate_packet
    except ImportError:
        return None
    errors = validate_packet(packet, catalog=retriever.catalog())
    if errors is None:
        return []
    if isinstance(errors, str):
        return [errors]
    return [str(item) for item in errors]


def _apply_repair(
    sections: Any,
    evidence: Any,
    amounts: Any,
    repaired: Any,
) -> tuple[Any, Any, Any]:
    if not isinstance(repaired, dict):
        return sections, evidence, amounts
    body = repaired.get("packet")
    if not isinstance(body, dict):
        body = repaired
    new_sections = body.get("sections")
    new_evidence = body.get("evidence_matrix")
    new_amounts = body.get("amounts")
    return (
        new_sections if isinstance(new_sections, dict) else sections,
        new_evidence if isinstance(new_evidence, list) else evidence,
        new_amounts if isinstance(new_amounts, list) else amounts,
    )


def _retrieve_passages(retriever: Any, queries: list[str]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for query in queries:
        try:
            hits = retriever.search(query, k=SEARCH_K)
        except Exception:
            continue
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            key = (hit.get("document_id"), hit.get("line_start"), hit.get("line_end"))
            if key in seen:
                continue
            seen.add(key)
            kept.append(hit)
            if len(kept) >= MAX_PASSAGES:
                return kept
    return kept


def _safe_catalog(retriever: Any) -> dict[str, Any]:
    try:
        catalog = retriever.catalog()
    except Exception:
        return {}
    return catalog if isinstance(catalog, dict) else {}


def _excerpt_text(
    retriever: Any,
    document_id: str,
    start: int,
    end: int,
    fallback: Any,
) -> str:
    text = ""
    try:
        text = retriever.lines(document_id, start, end)
    except Exception:
        text = ""
    if not isinstance(text, str) or not text.strip():
        text = fallback if isinstance(fallback, str) else ""
    text = text.strip()
    if len(text) > EXCERPT_CHAR_LIMIT:
        return text[:EXCERPT_CHAR_LIMIT] + "\n[excerto truncado]"
    return text


def _normalize_evidence(raw: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            proposition = entry.get("proposition")
            if not isinstance(proposition, str) or not proposition.strip():
                continue
            status, basis = _coerce_status(entry.get("status"), entry.get("basis"))
            item_id = entry.get("id")
            if not isinstance(item_id, str) or not item_id.strip() or item_id in seen:
                item_id = _fresh_evidence_id(seen)
            else:
                item_id = item_id.strip()
            seen.add(item_id)
            items.append(
                {
                    "id": item_id,
                    "proposition": proposition.strip(),
                    "status": status,
                    "basis": basis,
                }
            )
    if not items:
        items.append(
            {
                "id": "f01",
                "proposition": "Foi apresentado um registo para apreciação.",
                "status": "procedural",
                "basis": "procedural_record",
            }
        )
    if not any(item["status"] in {"proved", "procedural"} for item in items):
        item_id = _fresh_evidence_id({item["id"] for item in items})
        items.append(
            {
                "id": item_id,
                "proposition": "Há um registo processual sujeito a apreciação.",
                "status": "procedural",
                "basis": "procedural_record",
            }
        )
    if not any(item["status"] == "not_proved" for item in items):
        item_id = _fresh_evidence_id({item["id"] for item in items})
        items.append(
            {
                "id": item_id,
                "proposition": (
                    "Não ficou demonstrado o que o registo apenas afirma "
                    "unilateralmente ou remete para anexo não examinado."
                ),
                "status": "not_proved",
                "basis": "unilateral_assertion",
            }
        )
    return items


def _coerce_status(status: Any, basis: Any) -> tuple[str, str]:
    status_text = status if isinstance(status, str) else ""
    basis_text = basis if isinstance(basis, str) else ""
    if status_text == "proved" and basis_text in _PROVED_BASES:
        return status_text, basis_text
    if status_text == "procedural":
        return "procedural", "procedural_record"
    if status_text == "not_proved" and basis_text in _NOT_PROVED_BASES:
        return status_text, basis_text
    if status_text == "proved":
        return "not_proved", (
            basis_text if basis_text in _NOT_PROVED_BASES else "unilateral_assertion"
        )
    if basis_text in _NOT_PROVED_BASES:
        return "not_proved", basis_text
    return "not_proved", "unilateral_assertion"


def _fresh_evidence_id(used: set[str]) -> str:
    number = 1
    while True:
        candidate = f"f{number:02d}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        number += 1


def _coerce_sections(raw: Any) -> dict[str, list[dict[str, Any]]]:
    source = raw if isinstance(raw, dict) else {}
    sections: dict[str, list[dict[str, Any]]] = {}
    for key in SECTION_ORDER:
        items = source.get(key) or []
        if isinstance(items, str):
            items = [{"text": items}]
        if not isinstance(items, list):
            items = []
        cleaned: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            spec: dict[str, Any] = {"text": text.strip()}
            for field_name in ("source_ids", "evidence_ids"):
                values = item.get(field_name) or []
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    continue
                ids = [value.strip() for value in values if isinstance(value, str) and value.strip()]
                if ids:
                    spec[field_name] = ids
            cleaned.append(spec)
        sections[key] = cleaned
    return sections


def _ensure_minimums(
    sections: dict[str, list[dict[str, Any]]],
    evidence: list[dict[str, str]],
    source_ids: list[str],
) -> None:
    proved_ids = [
        item["id"] for item in evidence if item["status"] in {"proved", "procedural"}
    ]
    unproved_ids = [item["id"] for item in evidence if item["status"] == "not_proved"]
    if not sections["factos_provados"] and proved_ids:
        sections["factos_provados"] = [
            {
                "text": (
                    "Do registo resulta apenas o que a matriz classifica como "
                    "assente ou processual."
                ),
                "evidence_ids": [proved_ids[0]],
            }
        ]
    if not sections["factos_nao_provados"] and unproved_ids:
        sections["factos_nao_provados"] = [
            {
                "text": (
                    "Não se têm por demonstrados os factos que a matriz "
                    "classifica como não provados."
                ),
                "evidence_ids": [unproved_ids[0]],
            }
        ]
    for key, text in _FILLERS.items():
        if sections[key]:
            continue
        spec: dict[str, Any] = {"text": text}
        if key in LAW_SECTIONS and source_ids:
            spec["source_ids"] = [source_ids[0]]
        sections[key] = [spec]
    while len(sections["sumario"]) < 4:
        pad = _SUMARIO_PADS[len(sections["sumario"]) % len(_SUMARIO_PADS)]
        sections["sumario"].append({"text": pad})
    if len(sections["sumario"]) > 5:
        sections["sumario"] = sections["sumario"][:5]


def _clean_citations(
    sections: dict[str, list[dict[str, Any]]],
    evidence: list[dict[str, str]],
    allowed: dict[str, dict[str, Any]],
    flags: _Flags,
) -> None:
    statuses = {item["id"]: item["status"] for item in evidence}
    for section, specs in sections.items():
        for index, spec in enumerate(specs):
            source_ids = list(spec.get("source_ids") or [])
            kept_sources: list[str] = []
            removed_source = False
            for source_id in source_ids:
                if source_id in allowed and source_id not in kept_sources:
                    kept_sources.append(source_id)
                elif source_id not in allowed:
                    removed_source = True
            if removed_source:
                flags.source_stripped.add((section, index))
            if kept_sources:
                spec["source_ids"] = kept_sources
            else:
                spec.pop("source_ids", None)
            evidence_ids = list(spec.get("evidence_ids") or [])
            kept_evidence: list[str] = []
            removed_evidence = False
            for evidence_id in evidence_ids:
                status = statuses.get(evidence_id)
                if status is None:
                    removed_evidence = True
                    continue
                if section == "factos_provados" and status not in {"proved", "procedural"}:
                    removed_evidence = True
                    continue
                if section == "factos_nao_provados" and status != "not_proved":
                    removed_evidence = True
                    continue
                if evidence_id not in kept_evidence:
                    kept_evidence.append(evidence_id)
            if removed_evidence and section in _FACT_SECTIONS:
                flags.evidence_stripped.add((section, index))
            if kept_evidence:
                spec["evidence_ids"] = kept_evidence
            else:
                spec.pop("evidence_ids", None)


def _apply_prefixes(sections: dict[str, list[dict[str, Any]]]) -> None:
    for index, spec in enumerate(sections["sumario"]):
        text = _NUMBER_PREFIX.sub("", spec["text"].strip(), count=1).strip()
        spec["text"] = f"{index + 1}. {text}"
    for index, spec in enumerate(sections["factos_provados"]):
        text = _LETTER_PREFIX.sub("", spec["text"].strip(), count=1).strip()
        spec["text"] = f"{_proved_label(index)}) {text}"
    for index, spec in enumerate(sections["factos_nao_provados"]):
        text = _LETTER_PREFIX.sub("", spec["text"].strip(), count=1).strip()
        spec["text"] = f"{_unproved_label(index)}) {text}"


def _apply_quotes(
    sections: dict[str, list[dict[str, Any]]],
    allowed: dict[str, dict[str, Any]],
    retriever: Any,
    flags: _Flags,
) -> None:
    for section in LAW_SECTIONS:
        for index, spec in enumerate(sections.get(section) or []):
            cited = [
                allowed[source_id]
                for source_id in spec.get("source_ids") or []
                if source_id in allowed
            ]

            def verify(quote: str, cited_sources: list[dict[str, Any]] = cited) -> bool:
                return _quote_supported(retriever, cited_sources, quote)

            cleaned, failed = _strip_failed_quotes(spec.get("text") or "", verify)
            spec["text"] = cleaned
            if failed:
                flags.quote_failed.add((section, index))


def _quote_supported(
    retriever: Any,
    sources: list[dict[str, Any]],
    quote: str,
) -> bool:
    if not quote.strip():
        return False
    for source in sources:
        for start, end in _pinpoint_ranges(source.get("pinpoints") or []):
            try:
                if retriever.verify_quote(source["document_id"], start, end, quote):
                    return True
            except Exception:
                continue
    return False


def _strip_failed_quotes(text: str, verify: Any) -> tuple[str, bool]:
    failed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal failed
        inner = next(group for group in match.groups() if group is not None)
        if verify(inner):
            return match.group(0)
        failed = True
        return inner

    return _QUOTE_RE.sub(replace, text), failed


def _ensure_decision_tail(
    sections: dict[str, list[dict[str, Any]]],
    decision_total: str,
    case_value: str,
    place_and_date: str,
) -> None:
    blob = "\n".join(spec.get("text") or "" for spec in sections["decisao"])
    extra: list[str] = []
    if decision_total not in blob:
        extra.append(f"Total atribuído: {decision_total}.")
    if case_value not in blob:
        extra.append(f"Valor da causa: {case_value}.")
    if place_and_date not in blob:
        extra.append(f"{place_and_date}.")
    if extra:
        sections["decisao"].append({"text": " ".join(extra)})


def _normalize_amounts(raw: Any) -> tuple[list[dict[str, str]], str, str]:
    rows: list[dict[str, str]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            item = entry.get("item")
            item_text = item.strip() if isinstance(item, str) and item.strip() else "Pedido"
            reason = entry.get("reason")
            reason_text = (
                reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "Quantificação limitada ao registo."
            )
            claimed = _money_or_zero(entry.get("claimed"))
            awarded = _money_or_zero(entry.get("awarded"))
            if claimed < 0:
                claimed = Decimal("0.00")
            if awarded < 0:
                awarded = Decimal("0.00")
            if awarded > claimed:
                awarded = claimed
                note = "Valor atribuído limitado ao pedido."
                if note not in reason_text:
                    reason_text = f"{reason_text.rstrip()} {note}".strip()
            rows.append(
                {
                    "item": item_text,
                    "claimed": f"{claimed:.2f}",
                    "awarded": f"{awarded:.2f}",
                    "reason": reason_text,
                }
            )
    if not rows:
        rows.append(
            {
                "item": "Pedido sem quantia indicada",
                "claimed": "0.00",
                "awarded": "0.00",
                "reason": "O registo não quantifica o pedido.",
            }
        )
    claimed_total = sum((Decimal(row["claimed"]) for row in rows), Decimal("0.00"))
    awarded_total = sum((Decimal(row["awarded"]) for row in rows), Decimal("0.00"))
    return rows, f"{claimed_total:.2f}", f"{awarded_total:.2f}"


def _money_or_zero(value: Any) -> Decimal:
    try:
        return _parse_money(value)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _parse_money(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperation("montante em falta")
    if isinstance(value, Decimal):
        return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    text = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not text:
        raise InvalidOperation("montante vazio")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return Decimal(text).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _case_frame(case_meta: dict[str, Any] | None, matter: Any) -> dict[str, str]:
    meta = case_meta or {}
    matter = matter if isinstance(matter, dict) else {}
    process_number = str(meta.get("process_number") or "").strip() or "não indicado"
    title = str(meta.get("title") or "").strip() or "sem título"
    place = str(meta.get("place") or "").strip() or "Local não indicado"
    draft_raw = str(meta.get("draft_date") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", draft_raw):
        try:
            date.fromisoformat(draft_raw)
        except ValueError:
            draft_raw = date.today().isoformat()
        draft_date = draft_raw
    else:
        draft_date = date.today().isoformat()
    claimant_name, respondent_name = _party_names(matter)
    return {
        "process_number": process_number,
        "claimant": _party_label(claimant_name, "Reclamante não identificada"),
        "respondent": _party_label(respondent_name, "Reclamada não identificada"),
        "place_and_date": f"{place}, {_portuguese_date(draft_date)}",
        "draft_date": draft_date,
        "document_title": f"Minuta \u2014 {title}",
    }


def _party_names(matter: dict[str, Any]) -> tuple[str, str]:
    claimant = matter.get("claimant_name") if isinstance(matter.get("claimant_name"), str) else ""
    respondent = (
        matter.get("respondent_name") if isinstance(matter.get("respondent_name"), str) else ""
    )
    parties = matter.get("parties")
    if isinstance(parties, list):
        for party in parties:
            if not isinstance(party, dict):
                continue
            role = _fold(str(party.get("role") or ""))
            name = party.get("name_in_record") or party.get("name") or ""
            if not isinstance(name, str):
                name = ""
            if any(token in role for token in ("reclamant", "autor", "passageir")):
                claimant = claimant or name
            if any(token in role for token in ("reclamad", "transport", "recorrido")):
                respondent = respondent or name
    return claimant, respondent


def _party_label(value: str, anonymous: str) -> str:
    name = value.strip()
    folded = _fold(name)
    if not folded or folded in _ANONYMOUS or len(name) > 80:
        return anonymous
    if "\n" in name or "http" in folded:
        return anonymous
    return name


def _portuguese_date(iso_date: str) -> str:
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return f"{parsed.day} de {_MONTHS[parsed.month - 1]} de {parsed.year}"


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source["id"],
        "title": source["title"],
        "path": source["path"],
        "document_id": source["document_id"],
        "pinpoints": list(source["pinpoints"]),
    }


def _scrub_strings(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if "url" in str(key).lower():
                del value[key]
                continue
            value[key] = _scrub_strings(item)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _scrub_strings(item)
        return value
    if isinstance(value, str):
        return _URL_RE.sub("", value)
    return value


def _pinpoint_ranges(pinpoints: list[Any]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for item in pinpoints:
        if not isinstance(item, str):
            continue
        for match in _PIN_RE.finditer(item):
            if match.group(1):
                start, end = int(match.group(1)), int(match.group(2))
            else:
                start = end = int(match.group(3))
            if end < start:
                start, end = end, start
            ranges.append((start, end))
    return ranges


def _pinpoint(start: int, end: int) -> str:
    if start == end:
        return f"linha {start}"
    return f"linhas {start}\u2013{end}"


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[list[int]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _source_id(title: str, document_id: str, used: set[str]) -> str:
    base = _slugify(title) or _slugify(document_id) or "fonte"
    base = base[:32].strip("-") or "fonte"
    candidate = base
    number = 2
    while candidate in used:
        suffix = f"-{number}"
        candidate = f"{base[: 32 - len(suffix)].rstrip('-')}{suffix}"
        number += 1
    used.add(candidate)
    return candidate


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")
    parts = [part for part in text.split("-") if part and part not in _SLUG_STOP]
    return "-".join(parts[:5])[:32].strip("-")


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in text if not unicodedata.combining(char)).strip()


def _proved_label(index: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if index < 26:
        return alphabet[index]
    return alphabet[(index // 26) - 1] + alphabet[index % 26]


def _unproved_label(index: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return alphabet[index % 26] * 2


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = re.sub(r"\s+", " ", value.casefold())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _bounded_record(record_text: str) -> str:
    text = record_text if isinstance(record_text, str) else str(record_text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= RECORD_CHAR_LIMIT:
        return text
    return text[:RECORD_CHAR_LIMIT] + "\n[registo truncado neste pedido]"
