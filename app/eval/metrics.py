"""Scores for a Minutas decision packet.

Each scorer takes ``(packet, catalog, retriever=None, expected=None)`` and
returns ``ratio`` plus ``failures``. A ratio of 1.0 means every check passed.
``expected`` is the case file's ``expected`` object when the caller has one.

Citation lines and quoted spans are checked only when a retriever is given.
``validate_packet`` is imported lazily and omitted from the ratio when the
engine validator is not importable.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

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

# Same pairs as the packet reference and app.engine.validate.
STATUS_BASES = {
    "proved": {"common", "admission", "procedural_record"},
    "procedural": {"procedural_record"},
    "not_proved": {"unilateral_assertion", "unseen_attachment"},
}
PROVED_SECTION_STATUSES = {"proved", "procedural"}

MONEY = re.compile(r"^\d+\.\d{2}$")
PINPOINT_RE = re.compile(
    r"linhas?\s+(\d+)\s*[-\u2013\u2014]\s*(\d+)|linha\s+(\d+)",
    re.IGNORECASE,
)
QUOTE_RE = re.compile(
    r"«([^»]{12,})»|“([^”]{12,})”|\"([^\"\n]{12,})\""
)
LAW_SECTIONS = {"fundamentacao_direito"}


def _score(passed: int, checked: int, failures: list[str], **extra: Any) -> dict[str, Any]:
    ratio = 1.0 if passed == checked else (passed / checked)
    result: dict[str, Any] = {
        "ratio": ratio,
        "passed": passed,
        "checked": checked,
        "failures": failures,
    }
    result.update(extra)
    return result


def _sections(packet: dict[str, Any]) -> dict[str, list[Any]]:
    sections = packet.get("sections")
    if not isinstance(sections, dict):
        return {}
    return sections


def _paragraphs(packet: dict[str, Any], name: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    sections = _sections(packet)
    names = (name,) if name else tuple(sections)
    for section_name in names:
        content = sections.get(section_name)
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict):
                found.append((section_name, item))
    return found


def _norm_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").strip()


def _catalog_entry(catalog: dict[str, Any], document_id: str) -> dict[str, Any] | None:
    entry = catalog.get(document_id)
    if isinstance(entry, dict):
        return entry
    return None


def _path_matches(entry: dict[str, Any], packet_path: str) -> bool:
    wanted = _norm_path(packet_path)
    candidates = []
    for key in ("path", "rel_raw", "rel_source"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(_norm_path(value))
    return wanted in candidates


def _parse_pinpoints(pinpoints: Any) -> tuple[list[tuple[int, int]], list[str]]:
    ranges: list[tuple[int, int]] = []
    failures: list[str] = []
    if not isinstance(pinpoints, list):
        return ranges, ["pinpoints must be a list"]
    for raw in pinpoints:
        if not isinstance(raw, str):
            failures.append(f"unparsed pinpoint: {raw!r}")
            continue
        matched = False
        for match in PINPOINT_RE.finditer(raw):
            matched = True
            if match.group(3):
                line = int(match.group(3))
                ranges.append((line, line))
            else:
                start = int(match.group(1))
                end = int(match.group(2))
                if end < start:
                    failures.append(f"pinpoint end before start: {raw}")
                else:
                    ranges.append((start, end))
        if not matched:
            failures.append(f"unparsed pinpoint: {raw}")
    return ranges, failures


def _line_count(retriever: Any, document_id: str) -> int:
    if hasattr(retriever, "line_count"):
        return int(retriever.line_count(document_id))
    text = retriever.lines(document_id, 1, 10**9)
    if not isinstance(text, str) or text == "":
        return 0
    return len(text.splitlines())


def _quotes(text: str) -> list[str]:
    found: list[str] = []
    for match in QUOTE_RE.finditer(text or ""):
        quote = next(group for group in match.groups() if group)
        found.append(" ".join(quote.split()))
    return found


def citation_existence(
    packet: dict[str, Any],
    catalog: dict[str, Any],
    retriever: Any = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every source id is in the catalog and its path matches.

    With a retriever, pinpoint lines must fall inside the document and each
    quoted span in a law paragraph must verify against a cited source.
    """
    del expected
    failures: list[str] = []
    passed = 0
    checked = 0
    sources = packet.get("sources")
    if not isinstance(sources, list) or not sources:
        return _score(0, 1, ["sources must contain at least one local authority"])

    parsed: list[tuple[dict[str, Any], list[tuple[int, int]]]] = []
    for index, source in enumerate(sources):
        checked += 1
        prefix = f"sources[{index}]"
        if not isinstance(source, dict):
            failures.append(f"{prefix} must be an object")
            continue
        document_id = source.get("document_id")
        path = source.get("path")
        if not isinstance(document_id, str) or not document_id:
            failures.append(f"{prefix} has no document_id")
            continue
        entry = _catalog_entry(catalog, document_id)
        if entry is None:
            failures.append(f"{prefix} document_id absent from catalog: {document_id}")
            continue
        if not isinstance(path, str) or not _path_matches(entry, path):
            failures.append(
                f"{prefix} path does not match catalog for {document_id}: {path}"
            )
            continue
        ranges, pinpoint_failures = _parse_pinpoints(source.get("pinpoints"))
        if pinpoint_failures:
            failures.extend(f"{prefix}: {item}" for item in pinpoint_failures)
            continue
        passed += 1
        parsed.append((source, ranges))

    if retriever is not None:
        counts: dict[str, int] = {}
        for source, ranges in parsed:
            document_id = str(source["document_id"])
            if document_id not in counts:
                try:
                    counts[document_id] = _line_count(retriever, document_id)
                except Exception as exc:
                    counts[document_id] = -1
                    failures.append(f"{document_id}: line count failed: {exc}")
            total = counts[document_id]
            for start, end in ranges:
                checked += 1
                if total < 1 or start < 1 or end > total:
                    failures.append(
                        f"{document_id} pinpoint {start}-{end} outside 1..{total}"
                    )
                else:
                    passed += 1

        by_source_id = {
            str(source.get("id")): (source, ranges) for source, ranges in parsed
        }
        for section_name, paragraph in _paragraphs(packet):
            if section_name not in LAW_SECTIONS:
                continue
            text = paragraph.get("text") if isinstance(paragraph.get("text"), str) else ""
            quotes = _quotes(text)
            if not quotes:
                continue
            cited = paragraph.get("source_ids")
            if not isinstance(cited, list) or not cited:
                for quote in quotes:
                    checked += 1
                    failures.append(
                        f"{section_name} quotes without source_ids: {quote[:40]}"
                    )
                continue
            for quote in quotes:
                checked += 1
                verified = False
                for source_id in cited:
                    pair = by_source_id.get(str(source_id))
                    if pair is None:
                        continue
                    source, ranges = pair
                    document_id = str(source["document_id"])
                    spans = ranges or [(1, max(counts.get(document_id, 1), 1))]
                    for start, end in spans:
                        try:
                            if retriever.verify_quote(document_id, start, end, quote):
                                verified = True
                                break
                        except Exception:
                            verified = False
                    if verified:
                        break
                if verified:
                    passed += 1
                else:
                    failures.append(f"quote not in cited lines: {quote[:80]}")

    return _score(passed, checked, failures)


def _matrix(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    matrix = packet.get("evidence_matrix")
    if not isinstance(matrix, list):
        return rows
    for item in matrix:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            rows[item["id"]] = item
    return rows


def evidence_linkage(
    packet: dict[str, Any],
    catalog: dict[str, Any],
    retriever: Any = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fact paragraphs cite evidence ids whose status and basis are allowed.

    A proved-fact paragraph may cite ``proved`` or ``procedural`` evidence.
    An unproved-fact paragraph may cite only ``not_proved`` evidence.
    """
    del catalog, retriever, expected
    failures: list[str] = []
    passed = 0
    checked = 0
    rows = _matrix(packet)
    matrix = packet.get("evidence_matrix")
    if not isinstance(matrix, list) or not matrix:
        return _score(0, 1, ["evidence_matrix must contain entries"])

    for index, item in enumerate(matrix):
        checked += 1
        if not isinstance(item, dict):
            failures.append(f"evidence_matrix[{index}] must be an object")
            continue
        status = item.get("status")
        basis = item.get("basis")
        allowed = STATUS_BASES.get(status) if isinstance(status, str) else None
        if allowed is None or not isinstance(basis, str) or basis not in allowed:
            failures.append(
                f"evidence {item.get('id')} has incompatible status/basis: {status}/{basis}"
            )
        else:
            passed += 1

    expectations = {
        "factos_provados": PROVED_SECTION_STATUSES,
        "factos_nao_provados": {"not_proved"},
    }
    for section_name, allowed_statuses in expectations.items():
        content = _sections(packet).get(section_name)
        if not isinstance(content, list) or not content:
            checked += 1
            failures.append(f"sections.{section_name} has no fact paragraphs")
            continue
        for index, paragraph in enumerate(content):
            checked += 1
            prefix = f"sections.{section_name}[{index}]"
            if not isinstance(paragraph, dict):
                failures.append(f"{prefix} must be an object")
                continue
            evidence_ids = paragraph.get("evidence_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                failures.append(f"{prefix} needs evidence_ids")
                continue
            bad = False
            for evidence_id in evidence_ids:
                row = rows.get(evidence_id)
                if row is None:
                    failures.append(f"{prefix} cites unknown evidence {evidence_id}")
                    bad = True
                    continue
                status = row.get("status")
                basis = row.get("basis")
                if status not in allowed_statuses:
                    failures.append(
                        f"{prefix} cites {evidence_id} with status {status}"
                    )
                    bad = True
                    continue
                allowed_bases = STATUS_BASES.get(status, set())
                if basis not in allowed_bases:
                    failures.append(
                        f"{prefix} cites {evidence_id} with basis {basis}"
                    )
                    bad = True
            if not bad:
                passed += 1
    return _score(passed, checked, failures)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def amounts(
    packet: dict[str, Any],
    catalog: dict[str, Any],
    retriever: Any = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``decision_total`` equals the sum of awarded amounts.

    When ``expected['decision_total']`` is present, the packet total must
    equal that string exactly (two decimal places, dot separator).
    """
    del catalog, retriever
    failures: list[str] = []
    passed = 0
    checked = 0
    rows = packet.get("amounts")
    awarded_sum = Decimal("0.00")
    if not isinstance(rows, list) or not rows:
        failures.append("amounts must contain itemized claims")
        checked += 1
    else:
        for index, row in enumerate(rows):
            checked += 1
            prefix = f"amounts[{index}]"
            if not isinstance(row, dict):
                failures.append(f"{prefix} must be an object")
                continue
            awarded = _decimal(row.get("awarded"))
            claimed = _decimal(row.get("claimed")) if "claimed" in row else None
            if awarded is None:
                failures.append(f"{prefix}.awarded is not a decimal amount")
                continue
            if awarded < 0:
                failures.append(f"{prefix}.awarded is negative")
                continue
            if claimed is not None and awarded > claimed:
                failures.append(f"{prefix}.awarded exceeds claimed")
                continue
            awarded_sum += awarded
            passed += 1

    checked += 1
    total = packet.get("decision_total")
    total_dec = _decimal(total)
    if total_dec is None or not isinstance(total, str) or not MONEY.fullmatch(total.strip()):
        failures.append(f"decision_total is not a two-decimal string: {total!r}")
    elif total_dec.quantize(Decimal("0.01")) != awarded_sum.quantize(Decimal("0.01")):
        failures.append(
            f"decision_total {total} != sum of awarded {awarded_sum.quantize(Decimal('0.01'))}"
        )
    else:
        passed += 1

    expected_total = None
    exact: bool | None = None
    if isinstance(expected, dict) and "decision_total" in expected:
        expected_total = expected.get("decision_total")
        checked += 1
        exact = isinstance(total, str) and total.strip() == str(expected_total).strip()
        if exact:
            passed += 1
        else:
            failures.append(
                f"decision_total {total!r} != expected {expected_total!r}"
            )
    return _score(
        passed,
        checked,
        failures,
        exact=exact,
        decision_total=total if isinstance(total, str) else None,
        expected_total=expected_total,
    )


def _nonempty_paragraphs(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    kept: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            kept.append(item)
    return kept


def section_completeness(
    packet: dict[str, Any],
    catalog: dict[str, Any],
    retriever: Any = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every required section has text, and the sumário has four or five points."""
    del catalog, retriever, expected
    failures: list[str] = []
    passed = 0
    checked = 0
    sections = _sections(packet)
    for name in REQUIRED_SECTIONS:
        checked += 1
        if _nonempty_paragraphs(sections.get(name)):
            passed += 1
        else:
            failures.append(f"sections.{name} is empty")
    checked += 1
    summary = _nonempty_paragraphs(sections.get("sumario"))
    if len(summary) in {4, 5}:
        passed += 1
    else:
        failures.append(f"sections.sumario has {len(summary)} points; need 4 or 5")
    return _score(passed, checked, failures)


def _packet_prose(packet: dict[str, Any]) -> str:
    chunks: list[str] = []
    for _name, paragraph in _paragraphs(packet):
        text = paragraph.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


def must_mention(
    packet: dict[str, Any],
    catalog: dict[str, Any],
    retriever: Any = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Coverage of ``expected['must_mention']`` phrases in the drafted sections."""
    del catalog, retriever
    phrases: list[str] = []
    if isinstance(expected, dict) and isinstance(expected.get("must_mention"), list):
        phrases = [item for item in expected["must_mention"] if isinstance(item, str) and item.strip()]
    if not phrases:
        return _score(0, 0, [])
    haystack = _packet_prose(packet).casefold()
    failures: list[str] = []
    passed = 0
    for phrase in phrases:
        if phrase.casefold() in haystack:
            passed += 1
        else:
            failures.append(f"missing mention: {phrase}")
    return _score(passed, len(phrases), failures)


def validation_report(packet: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Error count from ``validate_packet`` when that function can be imported."""
    try:
        from app.engine.validate import validate_packet
    except ImportError as exc:
        return {"available": False, "count": None, "errors": [], "reason": str(exc)}
    try:
        errors = validate_packet(packet, catalog=catalog)
    except Exception as exc:
        return {
            "available": False,
            "count": None,
            "errors": [],
            "reason": f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(errors, list):
        return {
            "available": False,
            "count": None,
            "errors": [],
            "reason": "validate_packet did not return a list",
        }
    rendered = [str(item) for item in errors]
    return {"available": True, "count": len(rendered), "errors": rendered}


def evaluate(
    packet: dict[str, Any],
    catalog: dict[str, Any],
    retriever: Any = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every scorer plus the lazy packet validator."""
    return {
        "citation_existence": citation_existence(packet, catalog, retriever, expected),
        "evidence_linkage": evidence_linkage(packet, catalog, retriever, expected),
        "amounts": amounts(packet, catalog, retriever, expected),
        "section_completeness": section_completeness(packet, catalog, retriever, expected),
        "must_mention": must_mention(packet, catalog, retriever, expected),
        "validate_packet": validation_report(packet, catalog),
    }
