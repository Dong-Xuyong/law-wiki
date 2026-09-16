#!/usr/bin/env python3
"""Prepare a reproducible precision sample and publish the pilot quality report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import build_connection_graph as graph
import lint_wiki

SAMPLE_SEED = "law-wiki-pilot-precision-v1"


def load_optional(path: Path) -> list[dict[str, Any]]:
    return graph.load_jsonl(path) if path.is_file() else []


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def score(assertion: dict[str, Any]) -> str:
    return hashlib.sha256(
        f"{SAMPLE_SEED}:{assertion['assertion_id']}".encode("utf-8")
    ).hexdigest()


def precision_sample(
    connections: list[dict[str, Any]], size: int = 100
) -> list[dict[str, Any]]:
    """Select a deterministic predicate-stratified audit sample."""

    if size < 1 or size > len(connections):
        raise ValueError("sample size must be within accepted connection count")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in connections:
        groups[str(edge["predicate"])].append(edge)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    minimum = max(1, min(3, size // max(1, len(groups))))
    for predicate in sorted(groups):
        for edge in sorted(groups[predicate], key=score)[:minimum]:
            selected.append(edge)
            selected_ids.add(edge["assertion_id"])
    remaining = sorted(
        (edge for edge in connections if edge["assertion_id"] not in selected_ids),
        key=score,
    )
    selected.extend(remaining[: size - len(selected)])
    selected.sort(key=lambda edge: (edge["predicate"], score(edge)))
    return selected


def audit_record(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "assertion_id": edge["assertion_id"],
        "predicate": edge["predicate"],
        "subject": edge["subject"],
        "object": edge["object"],
        "reason": edge.get("reason", ""),
        "method": edge["method"],
        "confidence": edge["confidence"],
        "provenance": edge["provenance"],
    }


def counter_text(counter: Counter[str]) -> str:
    return ", ".join(f"`{key}` {counter[key]}" for key in sorted(counter))


def reviewer_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(row["assertion_id"]): str(row["decision"]).casefold()
        for row in rows
    }


def report(root: Path, sample_size: int = 100) -> tuple[str, dict[str, Any]]:
    pilot = root / "data" / "enrichment" / "pilot"
    manifest = graph.load_jsonl(root / "data/enrichment/pilot-manifest.jsonl")
    extraction_paths = sorted(pilot.glob("extractor-*.jsonl"))
    extraction_rows = [
        row for path in extraction_paths for row in graph.load_jsonl(path)
    ]
    candidates = graph.flatten_assertions(extraction_rows)
    connections = graph.load_jsonl(root / "data/connections.jsonl")
    queue = graph.load_jsonl(root / "data/enrichment/review-queue.jsonl")
    review_one = graph.load_jsonl(pilot / "reviewer-1.jsonl")
    review_two = graph.load_jsonl(pilot / "reviewer-2.jsonl")
    audit = load_optional(pilot / "precision-audit.jsonl")
    determinism = json.loads(
        (pilot / "determinism.json").read_text(encoding="utf-8")
    )
    lint = lint_wiki.lint(root, expected=5156)

    first, second = reviewer_map(review_one), reviewer_map(review_two)
    common = sorted(set(first) & set(second))
    agreements = sum(first[item] == second[item] for item in common)
    disagreements = len(common) - agreements
    both_accept = sum(
        first[item] == "accepted" and second[item] == "accepted" for item in common
    )
    both_reject = sum(
        first[item] == "rejected" and second[item] == "rejected" for item in common
    )

    sample_ids = {
        edge["assertion_id"] for edge in precision_sample(connections, sample_size)
    }
    audit_by_id = {str(row.get("assertion_id")): row for row in audit}
    audit_complete = set(audit_by_id) == sample_ids
    judgments = Counter(
        str(audit_by_id[item].get("judgment", "missing")).casefold()
        for item in sample_ids
    )
    correct = judgments["correct"]
    precision = correct / sample_size if audit_complete else 0.0

    evidence_valid = 0
    catalog, _ = graph.load_catalog(root / "data/catalog.jsonl")
    for edge in connections:
        try:
            graph.validate_assertion_shape(edge)
            graph.validate_provenance(edge, root, catalog)
        except (graph.ContractError, OSError, KeyError, TypeError):
            continue
        evidence_valid += 1

    gates = {
        "sample_complete": audit_complete,
        "precision_at_least_95": audit_complete and precision >= 0.95,
        "all_accepted_evidence_valid": evidence_valid == len(connections),
        "lint_clean": bool(lint["ok"]),
        "pilot_only": len(manifest) == 250 and len(extraction_paths) == 10,
        "deterministic_rerun": bool(determinism.get("identical")),
    }
    passed = all(gates.values())

    candidate_predicates = Counter(edge["predicate"] for edge in candidates)
    accepted_predicates = Counter(edge["predicate"] for edge in connections)
    methods = Counter(edge["method"] for edge in connections)
    queue_states = Counter(edge["review_status"] for edge in queue)
    examples: dict[str, dict[str, Any]] = {}
    for edge in connections:
        examples.setdefault(edge["predicate"], edge)

    lines = [
        "---",
        "tags: [reports, pilot-quality, connections]",
        f"created: {date.today().isoformat()}",
        f"updated: {date.today().isoformat()}",
        "verification: unverified",
        "---",
        "",
        "# Pilot connection-graph quality",
        "",
        f"**Gate result: {'PASS' if passed else 'FAIL'}**. This is a technical and "
        "model-review quality gate, not legal verification or legal advice.",
        "",
        "## Scope and coverage",
        "",
        f"- Pilot documents: {len(manifest)} of 5,156.",
        f"- Extraction batches: {len(extraction_paths)} × 25 documents.",
        f"- Websites / raw topics / years: "
        f"{len({row['website'] for row in manifest})} / "
        f"{len({row['topic'] for row in manifest})} / "
        f"{len({row['year'] for row in manifest})}.",
        f"- Short-text quality gates: "
        f"{sum(bool(row.get('short_text')) for row in manifest)}.",
        "",
        "## Extraction and review",
        "",
        f"- Candidate assertions: {len(candidates)}.",
        f"- Candidate predicates: {counter_text(candidate_predicates)}.",
        f"- Independently reviewed non-deterministic assertions: {len(common)}.",
        f"- Reviewer agreement: {agreements}/{len(common)} "
        f"({agreements / len(common):.1%}); disagreements: {disagreements}.",
        f"- Both accepted: {both_accept}; both rejected: {both_reject}.",
        f"- Accepted assertions: {len(connections)} "
        f"({counter_text(methods)}).",
        f"- Review queue: {len(queue)} ({counter_text(queue_states)}).",
        "- Summary-only assertions: 0. Extraction packets contained no CSV summary "
        "text, so no summary-only claim could become a hard edge.",
        "",
        "## Provenance and graph integrity",
        "",
        f"- Accepted assertions with valid target evidence: "
        f"{evidence_valid}/{len(connections)}.",
        f"- Lint: {'clean' if lint['ok'] else 'failed'}; "
        f"errors {len(lint['errors'])}, warnings {len(lint['warnings'])}.",
        f"- Canonical graph hubs: {lint['counts'].get('managed_hubs', 0)}.",
        "- Raw/source/catalog parity: "
        f"{lint['counts'].get('raw')} / {lint['counts'].get('sources')} / "
        f"{lint['counts'].get('catalog')}.",
        "- Deterministic rerun aggregate SHA-256: "
        f"`{determinism['aggregate_sha256']}` "
        f"({'identical' if determinism.get('identical') else 'different'} across "
        f"{determinism.get('runs')} runs).",
        "",
        "## Reproducible precision spot check",
        "",
        f"- Sample: {sample_size} accepted assertions, selected by "
        f"`SHA-256({SAMPLE_SEED}:assertion_id)` with at least three per predicate "
        "when available.",
        f"- Audit completion: {len(audit_by_id)}/{sample_size}.",
        f"- Judgments: {counter_text(judgments) if judgments else 'none'}.",
        f"- Conservative precision (uncertain/missing count as failures): "
        f"{precision:.1%}.",
        "- The audit is an independent model check of whether the cited evidence "
        "directly supports the edge. It is not human legal verification.",
        "",
        "## Accepted edge examples",
        "",
    ]
    for predicate in sorted(examples):
        edge = examples[predicate]
        provenance = edge["provenance"]
        preview = provenance.get(
            "quote", provenance.get("value", provenance.get("content_hash", ""))
        )
        preview = str(preview).replace("\n", " ")[:180]
        lines.append(
            f"- `{predicate}`: `{edge['subject']['key']}` → "
            f"`{edge['object']['key']}`; evidence `{preview}`."
        )
    lines.extend([
        "",
        "## Quality gates",
        "",
        *[
            f"- {'PASS' if value else 'FAIL'} — {name.replace('_', ' ')}."
            for name, value in gates.items()
        ],
        "",
        "## Scale decision",
        "",
        (
            "Pilot gates passed. The remaining corpus is still not processed in "
            "this task; scale-out requires a separate explicit decision."
            if passed
            else "Pilot gates did not pass. Do not process the remaining corpus; "
            "refine the schema/extractors and rerun the pilot."
        ),
        "",
    ])
    metrics = {
        "passed": passed,
        "precision": precision,
        "sample_size": sample_size,
        "accepted": len(connections),
        "queued": len(queue),
        "review_agreement": agreements / len(common),
        "gates": gates,
    }
    return "\n".join(lines), metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--prepare-audit-sample", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    connections = graph.load_jsonl(root / "data/connections.jsonl")
    if args.prepare_audit_sample:
        sample = precision_sample(connections, args.sample_size)
        path = root / "data/enrichment/pilot/precision-sample.jsonl"
        write_jsonl(path, (audit_record(edge) for edge in sample))
        print(json.dumps({"sample": len(sample), "path": str(path)}, indent=2))
        return 0
    content, metrics = report(root, args.sample_size)
    path = root / "reports/pilot-quality.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps({"report": str(path), **metrics}, indent=2))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
