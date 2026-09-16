#!/usr/bin/env python3
"""Validate, review, and materialize Law Wiki connection assertions.

Contracts:
* raw-span offsets address the normalized-LF payload after ``## Full text``;
* metadata evidence_hash is SHA-256 of ``str(value)`` encoded as UTF-8;
* assertion IDs hash canonical JSON of the edge identity and provenance;
* raw-span model/regex/lexical assertions require confidence >= 0.90 and two accepting reviewers;
* deterministic metadata/content-hash assertions are accepted after validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

GRAPH_BEGIN = "<!-- LAW-WIKI:GRAPH:BEGIN -->"
GRAPH_END = "<!-- LAW-WIKI:GRAPH:END -->"
FM_BEGIN = "# LAW-WIKI:GRAPH-FRONTMATTER:BEGIN"
FM_END = "# LAW-WIKI:GRAPH-FRONTMATTER:END"
CONFIDENCE_THRESHOLD = 0.90
LATERAL_PREDICATES = {
    "exact_duplicate_of", "same_case_as", "template_sibling_of",
    "semantically_similar_to",
}
SINGULAR_PREDICATES = {"document_of", "decided_by", "published_by", "has_outcome"}
ASSERTION_FIELDS = {
    "assertion_id", "subject", "predicate", "object", "source_document_id",
    "provenance", "method", "extractor_version", "confidence", "review_status",
    "reviewers", "reason",
}
PROCESSING_FIELDS = {"resolver_conflict", "cross_batch", "target_batch", "_batch"}
PREDICATES = {
    "document_of", "decided_by", "published_by", "about_sector",
    "about_doctrine", "about_topic", "cites_instrument", "cites_provision",
    "cites_authority", "has_outcome", "exact_duplicate_of", "same_case_as",
    "template_sibling_of", "semantically_similar_to", "mentions_entity",
}
METHODS = {"metadata", "regex", "content-hash", "lexical", "grok-4.6", "resolver"}
NODE_TYPES = {
    "document", "case", "forum", "organization", "sector", "doctrine", "topic",
    "instrument", "provision", "authority", "outcome", "family", "entity",
}


class ContractError(ValueError):
    """Raised when an input violates the graph contract."""


def normalize_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def full_text_payload(markdown: str) -> str:
    text = normalize_lf(markdown)
    match = re.search(r"(?m)^##[ \t]+Full text[ \t]*\n", text)
    if not match:
        raise ContractError("raw document has no level-2 Full text heading")
    payload = text[match.end():]
    if payload.startswith("\n"):
        payload = payload[1:]
    # Importer appends one framing newline which is not part of CSV text.
    return payload[:-1] if payload.endswith("\n") else payload


def sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assertion_identity(assertion: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": assertion["subject"]["key"],
        "predicate": assertion["predicate"],
        "object": assertion["object"]["key"],
        "source_document_id": assertion["source_document_id"],
        "provenance": assertion["provenance"],
    }


def compute_assertion_id(assertion: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical(assertion_identity(assertion)).encode("utf-8"))
    return "conn_" + digest.hexdigest()[:24]


def validate_assertion_shape(assertion: dict[str, Any]) -> None:
    required = {
        "subject", "predicate", "object", "source_document_id", "provenance",
        "method", "extractor_version", "confidence", "review_status",
    }
    missing = required - set(assertion)
    if missing:
        raise ContractError(f"assertion missing fields: {sorted(missing)}")
    if assertion["predicate"] not in PREDICATES:
        raise ContractError(f"unsupported predicate: {assertion['predicate']!r}")
    if assertion["method"] not in METHODS:
        raise ContractError(f"unsupported method: {assertion['method']!r}")
    confidence = assertion["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ContractError("confidence must be a number from 0 to 1")
    if assertion["review_status"] not in {
        "candidate", "accepted", "rejected", "disputed", "summary-only"
    }:
        raise ContractError("unsupported review status")
    if not re.fullmatch(r"law_[0-9a-f]{16}", str(assertion["source_document_id"])):
        raise ContractError("invalid source document id")
    for field in ("subject", "object"):
        node = assertion[field]
        if not isinstance(node, dict) or set(node) - {"key", "type", "label", "path"}:
            raise ContractError(f"invalid {field} node fields")
        if not all(str(node.get(name, "")).strip() for name in ("key", "type", "label")):
            raise ContractError(f"incomplete {field} node")
        if node["type"] not in NODE_TYPES:
            raise ContractError(f"invalid {field} node type")
    provenance = assertion["provenance"]
    if not isinstance(provenance, dict):
        raise ContractError("provenance must be an object")
    allowed = {
        "raw-span": {"kind", "raw_path", "section", "start", "end", "quote", "evidence_hash"},
        "metadata-field": {"kind", "field", "value", "evidence_hash"},
        "content-hash": {"kind", "content_hash", "peer_document_id"},
    }.get(provenance.get("kind"))
    if allowed is None or set(provenance) != allowed:
        raise ContractError("provenance fields do not match its kind")


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.casefold())).strip("-") or "item"


def canonical_node_path(node: dict[str, Any]) -> str | None:
    """Return the canonical wiki-relative path for materialized node types."""
    node_type = node.get("type")
    key = str(node.get("key", ""))
    label = str(node.get("label", key))
    leaf = slugify(key.split(":", 1)[-1] or label)
    folders = {
        "case": "cases", "instrument": "instruments", "family": "families",
        "organization": "entities", "forum": "entities", "entity": "entities",
        "authority": "entities", "sector": "concepts", "doctrine": "concepts",
        "topic": "concepts", "provision": "concepts", "outcome": "concepts",
    }
    folder = folders.get(node_type)
    return f"wiki/{folder}/{leaf}.md" if folder else node.get("path")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ContractError(f"missing JSONL: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ContractError(f"{path}:{number}: expected object")
        rows.append(value)
    return rows


def load_catalog(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    records = load_jsonl(path)
    by_id = {str(row["id"]): row for row in records}
    by_hash: dict[str, list[str]] = defaultdict(list)
    for row in records:
        by_hash[str(row.get("content_hash", ""))].append(str(row["id"]))
    return by_id, by_hash


def flatten_assertions(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(rows)
    batches = {
        str(row.get("document_id")): row.get("batch", row.get("batch_id"))
        for row in rows if row.get("document_id")
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        assertions = row.get("assertions")
        if isinstance(assertions, list):
            for assertion in assertions:
                copy = dict(assertion)
                copy.setdefault("source_document_id", row.get("document_id"))
                copy.setdefault("extractor_version", row.get("extractor_version", "unknown"))
                copy["_batch"] = row.get("batch", row.get("batch_id"))
                target = str(copy.get("object", {}).get("key", "")).removeprefix("document:")
                if target in batches:
                    copy["target_batch"] = batches[target]
                output.append(copy)
        else:
            output.append(dict(row))
    return output


def validate_provenance(
    assertion: dict[str, Any], root: Path, catalog: dict[str, dict[str, Any]]
) -> None:
    document_id = assertion.get("source_document_id")
    if document_id not in catalog:
        raise ContractError(f"unknown source document: {document_id}")
    subject = assertion.get("subject", {})
    if subject.get("type") != "document" or str(subject.get("key", "")).removeprefix("document:") != document_id:
        raise ContractError(f"{document_id}: subject does not identify source document")
    object_node = assertion.get("object", {})
    if object_node.get("type") == "document":
        target = str(object_node.get("key", "")).removeprefix("document:")
        if target not in catalog:
            raise ContractError(f"{document_id}: unknown document target {target}")
    record = catalog[document_id]
    provenance = assertion.get("provenance")
    if not isinstance(provenance, dict):
        raise ContractError("missing provenance object")
    kind = provenance.get("kind")
    if kind == "raw-span":
        raw_rel = str(provenance.get("raw_path", "")).replace("\\", "/")
        if not raw_rel.startswith("raw/documents/") or not raw_rel.endswith(".md"):
            raise ContractError(f"{document_id}: invalid raw evidence path")
        if provenance.get("section") not in {
            "header", "parties", "facts", "applicable-law", "reasoning",
            "disposition", "other",
        }:
            raise ContractError(f"{document_id}: invalid evidence section")
        if raw_rel != str(record.get("rel_raw", "")).replace("\\", "/"):
            raise ContractError(f"{document_id}: raw path does not match catalog")
        path = root / raw_rel
        payload = full_text_payload(path.read_text(encoding="utf-8"))
        start, end = provenance.get("start"), provenance.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(payload)):
            raise ContractError(f"{document_id}: invalid raw-span offsets")
        quote = provenance.get("quote")
        if payload[start:end] != quote:
            raise ContractError(f"{document_id}: raw-span quote mismatch")
        if sha256_text(quote) != provenance.get("evidence_hash"):
            raise ContractError(f"{document_id}: raw-span evidence hash mismatch")
    elif kind == "metadata-field":
        field, value = provenance.get("field"), provenance.get("value")
        if field not in {
            "id", "website", "folder", "filename", "year", "topic",
            "content_hash", "csv_row",
        }:
            raise ContractError(f"{document_id}: unsupported metadata field {field}")
        if field not in record or record[field] != value:
            raise ContractError(f"{document_id}: metadata evidence mismatch for {field}")
        if sha256_text(value) != provenance.get("evidence_hash"):
            raise ContractError(f"{document_id}: metadata evidence hash mismatch")
    elif kind == "content-hash":
        peer = provenance.get("peer_document_id")
        if peer not in catalog or peer == document_id:
            raise ContractError(f"{document_id}: invalid content-hash peer")
        claimed = provenance.get("content_hash")
        if claimed != record.get("content_hash") or claimed != catalog[peer].get("content_hash"):
            raise ContractError(f"{document_id}: content hashes do not match")
    else:
        raise ContractError(f"{document_id}: unknown provenance kind {kind!r}")


def _review_map(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        nested = row.get("reviews", row.get("assertions"))
        if isinstance(nested, list):
            result.update(_review_map(item for item in nested if isinstance(item, dict)))
            continue
        assertion_id = row.get("assertion_id")
        decision = row.get("decision", row.get("review_status", row.get("status")))
        if assertion_id and decision:
            result[str(assertion_id)] = str(decision).casefold()
    return result


def _is_accept(value: str | None) -> bool:
    return value in {"accept", "accepted", "approve", "approved"}


def _fold_support(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text)


def direct_support_rejection(assertion: dict[str, Any]) -> str | None:
    """Apply high-precision relation rules that reviewer consensus cannot waive."""

    predicate = assertion.get("predicate")
    provenance = assertion.get("provenance", {})
    if provenance.get("kind") != "raw-span":
        return None
    quote = str(provenance.get("quote", ""))
    folded_quote = _fold_support(quote)
    object_key = str(assertion.get("object", {}).get("key", ""))
    if predicate == "same_case_as":
        return "same-case links require provenance from both documents"
    if predicate == "document_of":
        if not object_key.startswith("case:pt:") or ":" not in object_key[8:]:
            return "case key is not forum plus process"
        forum_key, process_key = object_key.removeprefix("case:pt:").rsplit(":", 1)
        forum_tokens = [
            token for token in forum_key.split("-")
            if len(token) >= 4 and token not in {"tribunal", "arbitral", "consumo"}
        ]
        forum_named = any(_fold_support(token) in folded_quote for token in forum_tokens)
        process_present = _fold_support(process_key) in folded_quote
        adjudicative = any(
            marker in folded_quote
            for marker in ("tribunal", "arbitragem", "julgadodepaz")
        )
        if not (forum_named and process_present and adjudicative):
            return "single span does not directly establish both named forum and process"
    if predicate == "decided_by":
        forum_key = object_key.removeprefix("forum:pt:")
        forum_tokens = [
            token for token in forum_key.split("-")
            if len(token) >= 4 and token not in {"tribunal", "arbitral", "consumo"}
        ]
        forum_named = any(_fold_support(token) in folded_quote for token in forum_tokens)
        adjudicative = any(
            marker in folded_quote
            for marker in ("tribunal", "arbitragem", "julgadodepaz")
        )
        if not (forum_named and adjudicative):
            return "span names no specific deciding forum in adjudicative context"
    return None


def _queue_reasons(
    assertion: dict[str, Any], first: str | None, second: str | None
) -> list[str]:
    reasons: list[str] = []
    if float(assertion.get("confidence", 0)) < CONFIDENCE_THRESHOLD:
        reasons.append("low-confidence")
    if assertion.get("resolver_conflict"):
        reasons.append("resolver-conflict")
    if assertion.get("cross_batch") or (
        assertion.get("_batch") and assertion.get("target_batch")
        and assertion["_batch"] != assertion["target_batch"]
    ):
        reasons.append("cross-batch-link")
    if first != second:
        reasons.append("reviewer-disagreement")
    elif first is not None and not _is_accept(first):
        reasons.append("reviewer-rejected")
    direct_support = direct_support_rejection(assertion)
    if direct_support:
        reasons.append(f"direct-support: {direct_support}")
    return reasons


def adjudicate(
    assertions: Iterable[dict[str, Any]],
    reviewer_one: Iterable[dict[str, Any]],
    reviewer_two: Iterable[dict[str, Any]],
    root: Path,
    catalog: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviews_a, reviews_b = _review_map(reviewer_one), _review_map(reviewer_two)
    assertions = list(assertions)
    resolver_objects: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in assertions:
        if item.get("predicate") in SINGULAR_PREDICATES:
            resolver_objects[
                (str(item.get("source_document_id")), str(item.get("predicate")))
            ].add(str(item.get("object", {}).get("key")))
    for item in assertions:
        group = (str(item.get("source_document_id")), str(item.get("predicate")))
        if len(resolver_objects.get(group, set())) > 1:
            item["resolver_conflict"] = True
    accepted: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()
    for original in assertions:
        unknown = set(original) - ASSERTION_FIELDS - PROCESSING_FIELDS
        if unknown:
            raise ContractError(f"unsupported assertion fields: {sorted(unknown)}")
        assertion = {k: v for k, v in original.items() if k in ASSERTION_FIELDS}
        validate_assertion_shape(assertion)
        expected = compute_assertion_id(assertion)
        supplied = assertion.get("assertion_id")
        if supplied and supplied != expected:
            raise ContractError(f"assertion id mismatch: {supplied} != {expected}")
        assertion["assertion_id"] = expected
        if expected in seen:
            continue
        seen.add(expected)
        validate_provenance(assertion, root, catalog)
        first, second = reviews_a.get(expected), reviews_b.get(expected)
        reasons = _queue_reasons(original, first, second)
        provenance_kind = assertion["provenance"]["kind"]
        deterministic = (
            assertion.get("method") in {"metadata", "content-hash"}
            and provenance_kind in {"metadata-field", "content-hash"}
        )
        reviewed_ok = (
            assertion.get("method") in {"grok-4.6", "regex", "lexical", "resolver"}
            and provenance_kind == "raw-span"
            and float(assertion.get("confidence", 0)) >= CONFIDENCE_THRESHOLD
            and _is_accept(first) and _is_accept(second)
        )
        if (deterministic or reviewed_ok) and not reasons:
            assertion["review_status"] = "accepted"
            assertion["reviewers"] = sorted(
                set(assertion.get("reviewers", []))
                | ({"grok-reviewer-1", "grok-reviewer-2"} if reviewed_ok else set())
            )
            accepted.append(assertion)
        else:
            queued = dict(assertion)
            if "reviewer-disagreement" in reasons or "resolver-conflict" in reasons:
                queued["review_status"] = "disputed"
            elif "reviewer-rejected" in reasons or any(
                reason.startswith("direct-support:") for reason in reasons
            ):
                queued["review_status"] = "rejected"
            elif assertion.get("review_status") == "summary-only":
                queued["review_status"] = "summary-only"
            else:
                queued["review_status"] = "candidate"
            queue_reason = ", ".join(reasons or ["acceptance-rule-not-met"])
            prior_reason = queued.get("reason")
            queued["reason"] = (
                f"{prior_reason}; review queue: {queue_reason}"
                if prior_reason else f"review queue: {queue_reason}"
            )
            queue.append(queued)
    key = lambda row: row["assertion_id"]
    return sorted(accepted, key=key), sorted(queue, key=key)


def replace_managed(text: str, begin: str, end: str, content: str) -> str:
    if text.count(begin) != text.count(end) or text.count(begin) > 1:
        raise ContractError("unbalanced or duplicate graph-managed markers")
    block = f"{begin}\n{content.rstrip()}\n{end}"
    if begin in text:
        start, finish = text.index(begin), text.index(end) + len(end)
        return text[:start] + block + text[finish:]
    return text.rstrip() + "\n\n" + block + "\n"


def remove_managed(text: str, begin: str, end: str) -> str:
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ContractError("cannot remove unbalanced graph-managed markers")
    start, finish = text.index(begin), text.index(end) + len(end)
    return (text[:start].rstrip() + "\n" + text[finish:].lstrip()).rstrip() + "\n"


def _source_link(node: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> str | None:
    key = str(node.get("key", ""))
    doc_id = key.removeprefix("document:")
    row = catalog.get(doc_id)
    if not row:
        return None
    return str(row["rel_source"]).removeprefix("wiki/").removesuffix(".md")


def render_source(text: str, edges: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]) -> str:
    if text.startswith("---\n") and FM_BEGIN not in text:
        close = text.find("\n---", 4)
        if close < 0:
            raise ContractError("source frontmatter is not closed")
        frontmatter = text[:close]
        managed = f"{FM_BEGIN}\nenrichment_state: graph-reviewed\n{FM_END}"
        updated, count = re.subn(
            r"(?m)^enrichment_state:\s*.*$",
            managed,
            frontmatter,
            count=1,
        )
        if count:
            text = updated + text[close:]
        else:
            text = frontmatter + "\n" + managed + text[close:]
    elif FM_BEGIN in text:
        text = replace_managed(text, FM_BEGIN, FM_END, "enrichment_state: graph-reviewed")
    lines = ["## Graph connections", "", "Model-reviewed graph assertions; legal verification remains unverified."]
    lateral = 0
    for edge in sorted(edges, key=lambda e: (e["predicate"], e["object"]["key"])):
        path = canonical_node_path(edge["object"])
        if edge["predicate"] in LATERAL_PREDICATES:
            if lateral >= 3:
                continue
            target = _source_link(edge["object"], catalog)
            reason = str(edge.get("reason", "")).strip()
            if not target or not reason:
                continue
            lateral += 1
            lines.append(f"- [[{target}|{edge['object']['label']}]] — {reason}")
        elif path:
            target = path.removeprefix("wiki/").removesuffix(".md")
            lines.append(f"- {edge['predicate'].replace('_', ' ')}: [[{target}|{edge['object']['label']}]]")
    return replace_managed(text, GRAPH_BEGIN, GRAPH_END, "\n".join(lines))


def render_hub(node: dict[str, Any], incoming: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]) -> str:
    lines = [
        f"# {node['label']}", "", "## Connected sources", "",
        "Graph-derived links; underlying source pages remain unverified.",
    ]
    for edge in sorted(incoming, key=lambda e: e["source_document_id"]):
        row = catalog[edge["source_document_id"]]
        target = str(row["rel_source"]).removeprefix("wiki/").removesuffix(".md")
        lines.append(f"- [[{target}|{row.get('filename', row['id'])}]] — {edge['predicate'].replace('_', ' ')}")
    return f"---\nverification: unverified\nenrichment_state: graph-reviewed\n---\n\n{GRAPH_BEGIN}\n" + "\n".join(lines) + f"\n{GRAPH_END}\n"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(_canonical(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
    )


def materialize(
    root: Path, output_root: Path, accepted: list[dict[str, Any]],
    queue: list[dict[str, Any]], catalog: dict[str, dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    changes: dict[str, str] = {}
    if not dry_run:
        write_jsonl(output_root / "data/connections.jsonl", accepted)
        write_jsonl(output_root / "data/enrichment/review-queue.jsonl", queue)
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    nodes: dict[str, dict[str, Any]] = {}
    for edge in accepted:
        by_source[edge["source_document_id"]].append(edge)
        path = canonical_node_path(edge["object"])
        if path and edge["object"].get("type") != "document":
            by_node[path].append(edge)
            nodes[path] = edge["object"]
    for document_id, edges in by_source.items():
        rel = Path(str(catalog[document_id]["rel_source"]))
        source = root / rel
        rendered = render_source(source.read_text(encoding="utf-8"), edges, catalog)
        changes[rel.as_posix()] = rendered
    for rel, edges in by_node.items():
        destination = output_root / rel
        existing = destination.read_text(encoding="utf-8") if destination.is_file() else ""
        generated = render_hub(nodes[rel], edges, catalog)
        if existing:
            managed = generated.split(GRAPH_BEGIN, 1)[1].split(GRAPH_END, 1)[0].strip()
            generated = replace_managed(existing, GRAPH_BEGIN, GRAPH_END, managed)
        changes[rel] = generated
    if not dry_run:
        for rel, rendered in changes.items():
            destination = output_root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8", newline="\n")
        desired_hubs = set(by_node)
        for folder in ("cases", "instruments", "families", "entities", "concepts"):
            directory = output_root / "wiki" / folder
            if not directory.is_dir():
                continue
            for path in directory.glob("*.md"):
                rel = path.relative_to(output_root).as_posix()
                if rel in desired_hubs:
                    continue
                text = path.read_text(encoding="utf-8")
                if GRAPH_BEGIN not in text:
                    continue
                graph_only = re.fullmatch(
                    r"---\nverification: unverified\nenrichment_state: graph-reviewed\n---"
                    r"\n\n<!-- LAW-WIKI:GRAPH:BEGIN -->.*"
                    r"<!-- LAW-WIKI:GRAPH:END -->\n?",
                    normalize_lf(text),
                    re.DOTALL,
                )
                if graph_only:
                    path.unlink()
                else:
                    path.write_text(
                        remove_managed(text, GRAPH_BEGIN, GRAPH_END),
                        encoding="utf-8",
                        newline="\n",
                    )
                changes[rel] = "<removed stale graph-managed content>"
    return {"accepted": len(accepted), "queued": len(queue), "changed_pages": sorted(changes)}


def build_graph(
    root: Path, extraction_paths: list[Path], reviewer_paths: list[Path],
    output_root: Path | None = None, dry_run: bool = False,
) -> dict[str, Any]:
    if len(reviewer_paths) != 2:
        raise ContractError("exactly two reviewer JSONL files are required")
    root = root.resolve()
    output_root = (output_root or root).resolve()
    catalog, _ = load_catalog(root / "data/catalog.jsonl")
    assertions = flatten_assertions(row for path in extraction_paths for row in load_jsonl(path))
    accepted, queue = adjudicate(
        assertions, load_jsonl(reviewer_paths[0]), load_jsonl(reviewer_paths[1]), root, catalog
    )
    return materialize(root, output_root, accepted, queue, catalog, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--extraction", type=Path, action="append", required=True)
    parser.add_argument("--reviewer", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        report = build_graph(
            args.root, args.extraction, args.reviewer, args.output_root, args.dry_run
        )
    except (ContractError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
