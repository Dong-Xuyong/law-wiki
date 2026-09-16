#!/usr/bin/env python3
"""Select a small, deterministic, risk-diverse enrichment pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

EXPECTED_WEBSITES = 6
EXPECTED_TOPICS = 22
EXPECTED_YEARS = 11
EXPECTED_SHORT_RECORDS = 28
MAX_PROCESS_CONFLICT_STRATA = 20


def load_catalog(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def tie(seed: int, record: dict[str, Any]) -> str:
    return hashlib.sha256(f"{seed}:{record['id']}".encode()).hexdigest()


def add(
    selected: list[dict[str, Any]],
    selected_ids: set[str],
    record: dict[str, Any],
    reason: str,
    count: int,
) -> None:
    if record["id"] in selected_ids:
        for item in selected:
            if item["id"] == record["id"] and reason not in item["selection_reasons"]:
                item["selection_reasons"].append(reason)
        return
    if len(selected) >= count:
        return
    copy = dict(record)
    copy["selection_reasons"] = [reason]
    selected.append(copy)
    selected_ids.add(record["id"])


def _fold(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value).casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", folded)


def _truthy(value: Any) -> bool:
    return value is True or str(value).casefold() in {"1", "true", "yes"}


def _is_supplied(record: dict[str, Any]) -> bool:
    return record.get("website") == "Fornecidos" or "fornecid" in _fold(record.get("topic", ""))


def _is_legislation(record: dict[str, Any]) -> bool:
    return "legisl" in _fold(record.get("topic", "")) or "legisl" in _fold(record.get("folder", ""))


def _is_ocr_poor(record: dict[str, Any]) -> bool:
    return _truthy(record.get("ocr_poor")) or str(record.get("text_quality", "")).casefold() == "ocr-poor"


def _is_ordinary_decision(record: dict[str, Any]) -> bool:
    if _is_ocr_poor(record) or _truthy(record.get("short_text")):
        return False
    types = record.get("document_types", [])
    values = {
        item.get("value") if isinstance(item, dict) else item
        for item in types
    }
    name = _fold(record.get("filename", ""))
    return bool(values & {"sentença", "acórdão", "decisão", "despacho"}) or any(
        marker in name for marker in ("sent", "acord", "decis", "despacho")
    )


def exact_duplicate_groups(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("content_hash"):
            by_hash[str(record["content_hash"])].append(record)
    return [
        sorted(group, key=lambda row: str(row["id"]))
        for _, group in sorted(by_hash.items())
        if len(group) > 1
    ]


def process_conflict_groups(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Same extracted process key with conflicting content is a review risk."""

    by_process: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        keys = record.get("process_keys") or []
        if isinstance(keys, str):
            keys = [keys]
        for key in {_fold(value) for value in keys if value}:
            by_process[key].append(record)
    groups = []
    for _, group in sorted(by_process.items()):
        unique = {row["id"]: row for row in group}
        if len({row.get("content_hash") for row in unique.values()}) > 1:
            groups.append(sorted(unique.values(), key=lambda row: str(row["id"])))
    return groups


def representative_process_conflicts(
    records: list[dict[str, Any]], maximum: int = MAX_PROCESS_CONFLICT_STRATA
) -> list[list[dict[str, Any]]]:
    """Bound noisy process-number collisions to reviewable conflict strata."""

    groups = [
        group for group in process_conflict_groups(records)
        if 2 <= len(group) <= 5
    ]
    groups.sort(key=lambda group: (
        -len({row.get("website") for row in group}),
        -len({row.get("topic") for row in group}),
        len(group),
        tuple(row["id"] for row in group),
    ))
    return groups[:maximum]


def _coverage_tokens(record: dict[str, Any]) -> set[tuple[str, str]]:
    tokens = {
        ("website", str(record.get("website", ""))),
        ("topic", str(record.get("topic", ""))),
        ("year", str(record.get("year", ""))),
    }
    if _is_supplied(record):
        tokens.add(("risk", "supplied"))
    if _is_legislation(record):
        tokens.add(("risk", "legislation"))
    if _is_ocr_poor(record):
        tokens.add(("risk", "ocr-poor"))
    if _is_ordinary_decision(record):
        tokens.add(("risk", "ordinary-decision"))
    return tokens


def required_coverage(records: list[dict[str, Any]]) -> set[tuple[str, str]]:
    required = {
        (kind, str(record.get(kind, "")))
        for kind in ("website", "topic", "year")
        for record in records
    }
    for risk, predicate in (
        ("supplied", _is_supplied),
        ("legislation", _is_legislation),
        ("ocr-poor", _is_ocr_poor),
        ("ordinary-decision", _is_ordinary_decision),
    ):
        if any(predicate(record) for record in records):
            required.add(("risk", risk))
    return required


def validate_corpus_dimensions(records: list[dict[str, Any]]) -> None:
    observed = {
        "websites": len({row.get("website") for row in records}),
        "topics": len({row.get("topic") for row in records}),
        "years": len({str(row.get("year")) for row in records}),
        "short_records": sum(_truthy(row.get("short_text")) for row in records),
    }
    expected = {
        "websites": EXPECTED_WEBSITES,
        "topics": EXPECTED_TOPICS,
        "years": EXPECTED_YEARS,
        "short_records": EXPECTED_SHORT_RECORDS,
    }
    if observed != expected:
        raise ValueError(f"catalog coverage dimensions changed: expected {expected}, observed {observed}")


def validate_selection(
    records: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> None:
    selected_ids = {row["id"] for row in selected}
    missing_short = [
        row["id"] for row in records
        if _truthy(row.get("short_text")) and row["id"] not in selected_ids
    ]
    covered = set().union(*(_coverage_tokens(row) for row in selected)) if selected else set()
    missing = sorted(required_coverage(records) - covered)
    conflicts = representative_process_conflicts(records)
    missing_conflicts = [
        [row["id"] for row in group]
        for group in conflicts
        if not any(row["id"] in selected_ids for row in group)
    ]
    missing_duplicates = [
        [row["id"] for row in group]
        for group in exact_duplicate_groups(records)
        if not any(row["id"] in selected_ids for row in group)
    ]
    if missing_short or missing or missing_conflicts or missing_duplicates:
        raise ValueError(
            "required pilot coverage impossible at requested count: "
            f"missing_short={missing_short}, missing={missing}, "
            f"missing_process_conflicts={missing_conflicts}, "
            f"missing_duplicate_groups={missing_duplicates}"
        )


def choose_pilot(
    records: list[dict[str, Any]], count: int = 250, seed: int = 46
) -> list[dict[str, Any]]:
    if count < 1 or count > len(records):
        raise ValueError(f"count must be between 1 and {len(records)}")

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    # Every short record is a mandatory quality gate.
    for record in sorted(
        (row for row in records if _truthy(row.get("short_text"))),
        key=lambda row: (int(row.get("text_chars", 0)), tie(seed, row)),
    ):
        add(selected, selected_ids, record, "all-short-text-records", count)
    if sum(_truthy(row.get("short_text")) for row in records) > count:
        raise ValueError("count is too small to include every short-text record")

    # Greedy set cover over every observed website/topic/year and available
    # risk class. The tie-breaker is seeded but stable.
    uncovered = required_coverage(records) - set().union(
        *(_coverage_tokens(row) for row in selected)
    ) if selected else required_coverage(records)
    while uncovered and len(selected) < count:
        candidates = [row for row in records if row["id"] not in selected_ids]
        candidates.sort(
            key=lambda row: (
                -len(_coverage_tokens(row) & uncovered),
                abs(int(row.get("text_chars", 0)) - 15000),
                tie(seed, row),
            )
        )
        if not candidates or not (_coverage_tokens(candidates[0]) & uncovered):
            break
        gained = sorted(_coverage_tokens(candidates[0]) & uncovered)
        add(selected, selected_ids, candidates[0], "coverage:" + ",".join(f"{a}={b}" for a, b in gained), count)
        uncovered -= _coverage_tokens(candidates[0])

    # Represent every duplicate group, then prefer complete groups whenever
    # capacity permits. Rows remain separate and are never silently merged.
    groups = exact_duplicate_groups(records)
    groups.sort(key=lambda group: (len(group), tuple(row["id"] for row in group)))
    for index, group in enumerate(groups, 1):
        if not any(row["id"] in selected_ids for row in group):
            candidates = sorted(group, key=lambda row: tie(seed, row))
            add(selected, selected_ids, candidates[0], f"exact-duplicate-representative:{index}", count)
    for index, group in enumerate(groups, 1):
        missing = [row for row in group if row["id"] not in selected_ids]
        if len(missing) <= count - len(selected):
            for record in missing:
                add(selected, selected_ids, record, f"exact-duplicate-group:{index}", count)

    # Process-number parsing is deliberately broad and produces many common
    # numeric collisions. Include a bounded, diversity-ranked conflict sample
    # rather than allowing noisy collisions to consume the entire pilot.
    for index, group in enumerate(representative_process_conflicts(records), 1):
        candidates = [row for row in group if row["id"] not in selected_ids]
        if candidates:
            candidates.sort(key=lambda row: tie(seed, row))
            add(selected, selected_ids, candidates[0], f"process-conflict:{index}", count)

    # Fill remaining slots with ordinary, size-bounded, diverse records.
    while len(selected) < count:
        used_topics = {r.get("topic") for r in selected}
        used_years = {r.get("year") for r in selected}
        used_websites = {r.get("website") for r in selected}
        candidates = [
            r
            for r in records
            if r["id"] not in selected_ids
            and 500 <= int(r.get("text_chars", 0)) <= 60000
        ]
        if not candidates:
            candidates = [r for r in records if r["id"] not in selected_ids]
        candidates.sort(
            key=lambda r: (
                r.get("topic") in used_topics,
                r.get("year") in used_years,
                r.get("website") in used_websites,
                abs(int(r.get("text_chars", 0)) - 15000),
                tie(seed, r),
            )
        )
        add(selected, selected_ids, candidates[0], "diverse-topic-year", count)

    validate_selection(records, selected)
    return selected


def manifest_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "id",
        "folder",
        "filename",
        "year",
        "website",
        "topic",
        "tokens",
        "tokens_sm",
        "content_hash",
        "rel_raw",
        "rel_source",
        "source_slug",
        "text_chars",
        "summary_chars",
        "short_text",
        "selection_reasons",
    }
    output = {key: record.get(key) for key in keep}
    output["raw_path"] = str((root / record["rel_raw"]).resolve())
    output["source_path"] = str((root / record["rel_source"]).resolve())
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--seed", type=int, default=46)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/enrichment/pilot-manifest.jsonl"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    records = load_catalog(root / "data" / "catalog.jsonl")
    evidence_path = root / "data" / "enrichment" / "legal-signals.jsonl"
    if evidence_path.exists():
        evidence = {row["id"]: row for row in load_catalog(evidence_path)}
        for record in records:
            signal = evidence.get(record["id"], {})
            for key in ("process_keys", "ocr_poor", "document_types"):
                if key in signal:
                    record[key] = signal[key]
    validate_corpus_dimensions(records)
    selected = choose_pilot(records, args.count, args.seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in selected:
            handle.write(
                json.dumps(manifest_record(root, record), ensure_ascii=False) + "\n"
            )
    print(json.dumps({"selected": len(selected), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
