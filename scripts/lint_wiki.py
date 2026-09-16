#!/usr/bin/env python3
"""Read-only structural and provenance lint for a Law Wiki graph."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import build_connection_graph as graph

WIKILINK_RE = re.compile(r"\[\[([^]|#]+)")
FM_RE = re.compile(r"\A---\n(.*?)\n---(?:\n|$)", re.DOTALL)


def _jsonl_optional(path: Path) -> list[dict[str, Any]]:
    return graph.load_jsonl(path) if path.is_file() else []


def _frontmatter(text: str) -> dict[str, str]:
    match = FM_RE.match(graph.normalize_lf(text))
    if not match:
        return {}
    output: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            output[key.strip()] = value.strip().strip("\"'")
    return output


def _target_exists(root: Path, source: Path, target: str) -> bool:
    clean = target.strip().replace("\\", "/")
    suffix = "" if clean.casefold().endswith(".md") else ".md"
    candidates = [
        root / "wiki" / (clean + suffix),
        source.parent / (clean + suffix),
        root / (clean + suffix),
    ]
    return any(path.resolve().is_file() for path in candidates)


def lint(root: Path, expected: int | None = None) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    catalog_path = root / "data/catalog.jsonl"
    try:
        base_catalog_rows = graph.load_jsonl(catalog_path)
        pdf_catalog_path = root / "data/pdf-catalog.jsonl"
        pdf_catalog_rows = graph.load_jsonl(pdf_catalog_path) if pdf_catalog_path.exists() else []
        catalog_rows = [*base_catalog_rows, *pdf_catalog_rows]
    except (graph.ContractError, OSError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "counts": {}}
    catalog = {str(row["id"]): row for row in catalog_rows}
    raw_files = list((root / "raw/documents").rglob("*.md"))
    source_files = list((root / "wiki/sources").glob("*.md"))
    if expected is not None and len(base_catalog_rows) != expected:
        errors.append(f"base catalog rows {len(base_catalog_rows)} != {expected}")
    if len(raw_files) != len(catalog_rows):
        errors.append(f"raw/catalog parity: {len(raw_files)} != {len(catalog_rows)}")
    if len(source_files) != len(catalog_rows):
        errors.append(f"source/catalog parity: {len(source_files)} != {len(catalog_rows)}")
    ids = [str(row.get("id")) for row in catalog_rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate catalog document ids")
    for row in catalog_rows:
        for field in ("rel_raw", "rel_source"):
            rel = row.get(field)
            if not rel or not (root / str(rel)).is_file():
                errors.append(f"{row.get('id')}: missing {field} target {rel}")
        source_path = root / str(row.get("rel_source", ""))
        raw_path = root / str(row.get("rel_raw", ""))
        if source_path.is_file():
            source_fm = _frontmatter(source_path.read_text(encoding="utf-8"))
            expected_source = {
                "id": str(row["id"]),
                "content_hash": str(row.get("content_hash", "")),
                "raw": str(row.get("rel_raw", "")).replace("\\", "/"),
            }
            for field, expected_value in expected_source.items():
                actual = source_fm.get(field)
                if actual is not None and actual.replace("\\", "/") != expected_value:
                    errors.append(f"{row['id']}: protected source {field} mismatch")
        if raw_path.is_file():
            raw_text = raw_path.read_text(encoding="utf-8")
            raw_fm = _frontmatter(raw_text)
            for field in ("id", "content_hash"):
                if raw_fm.get(field) is not None and raw_fm[field] != str(row.get(field, "")):
                    errors.append(f"{row['id']}: raw {field} mismatch")
            try:
                payload_hash = graph.sha256_text(graph.full_text_payload(raw_text))
                if payload_hash != str(row.get("content_hash", "")):
                    errors.append(f"{row['id']}: raw payload content_hash mismatch")
            except graph.ContractError as exc:
                errors.append(f"{row['id']}: {exc}")

    connections = _jsonl_optional(root / "data/connections.jsonl")
    queue = _jsonl_optional(root / "data/enrichment/review-queue.jsonl")
    paths_to_keys: dict[str, set[str]] = defaultdict(set)
    incoming: Counter[str] = Counter()
    edge_ids: set[str] = set()
    for edge in connections:
        assertion_id = str(edge.get("assertion_id", ""))
        if assertion_id in edge_ids:
            errors.append(f"duplicate assertion id {assertion_id}")
        edge_ids.add(assertion_id)
        try:
            if graph.compute_assertion_id(edge) != assertion_id:
                errors.append(f"{assertion_id}: non-deterministic assertion id")
            graph.validate_provenance(edge, root, catalog)
        except (graph.ContractError, KeyError, TypeError, OSError) as exc:
            errors.append(f"{assertion_id or '<unknown>'}: {exc}")
        if edge.get("review_status") != "accepted":
            errors.append(f"{assertion_id}: connection is not accepted")
        for node_name in ("subject", "object"):
            node = edge.get(node_name, {})
            path = graph.canonical_node_path(node)
            if path:
                paths_to_keys[path.casefold()].add(str(node.get("key")))
                if node.get("type") != "document":
                    incoming[path] += 1
                    if not (root / path).is_file():
                        errors.append(f"{assertion_id}: missing canonical target {path}")
    for path, keys in paths_to_keys.items():
        if len(keys) > 1:
            errors.append(f"canonical collision at {path}: {sorted(keys)}")

    for item in queue:
        assertion_id = str(item.get("assertion_id", ""))
        try:
            if graph.compute_assertion_id(item) != assertion_id:
                errors.append(f"{assertion_id}: non-deterministic queued assertion id")
            graph.validate_assertion_shape(item)
            graph.validate_provenance(item, root, catalog)
        except (graph.ContractError, KeyError, TypeError, OSError) as exc:
            errors.append(f"{assertion_id or '<unknown>'}: invalid review item: {exc}")
        if item.get("review_status") == "accepted":
            errors.append(f"{item.get('assertion_id')}: accepted edge left in review queue")
        if "review queue:" not in str(item.get("reason", "")):
            errors.append(f"{item.get('assertion_id')}: review item has no queue reason")

    by_hash: dict[str, list[str]] = defaultdict(list)
    duplicate_edges: set[frozenset[str]] = set()
    for row in catalog_rows:
        by_hash[str(row.get("content_hash", ""))].append(str(row["id"]))
    for edge in connections:
        if edge.get("predicate") == "exact_duplicate_of":
            left = str(edge.get("source_document_id"))
            right = str(edge.get("object", {}).get("key", "")).removeprefix("document:")
            duplicate_edges.add(frozenset((left, right)))
    for content_hash, members in by_hash.items():
        if content_hash and len(members) > 1:
            anchor = members[0]
            for peer in members[1:]:
                importer_linked = False
                anchor_row, peer_row = catalog[anchor], catalog[peer]
                for left, right in ((anchor_row, peer_row), (peer_row, anchor_row)):
                    source_path = root / str(left.get("rel_source", ""))
                    if not source_path.is_file():
                        continue
                    duplicate_of = _frontmatter(
                        source_path.read_text(encoding="utf-8")
                    ).get("duplicate_of", "")
                    peer_slug = str(right.get("source_slug", ""))
                    peer_rel = str(right.get("rel_source", "")).removeprefix("wiki/").removesuffix(".md")
                    if (peer_slug and peer_slug in duplicate_of) or peer_rel in duplicate_of:
                        importer_linked = True
                        break
                if frozenset((anchor, peer)) not in duplicate_edges and not importer_linked:
                    errors.append(f"duplicate cluster missing edge: {anchor}, {peer}")

    catalog_topics = {str(row.get("topic", "")).strip() for row in catalog_rows if row.get("topic")}
    covered_topics = {
        str(edge.get("object", {}).get("label", "")).strip()
        for edge in connections if edge.get("predicate") == "about_topic"
    }
    for topic in sorted(catalog_topics - covered_topics):
        warnings.append(f"topic has no graph edge: {topic}")

    all_markdown = list((root / "wiki").rglob("*.md"))
    managed_hubs: set[str] = set()
    for path in all_markdown:
        text = graph.normalize_lf(path.read_text(encoding="utf-8"))
        for begin, end in (
            (graph.GRAPH_BEGIN, graph.GRAPH_END),
            (graph.FM_BEGIN, graph.FM_END),
        ):
            if text.count(begin) != text.count(end) or text.count(begin) > 1:
                errors.append(f"marker imbalance: {path.relative_to(root).as_posix()}")
        links = WIKILINK_RE.findall(text)
        for target in links:
            if not _target_exists(root, path, target):
                errors.append(
                    f"broken wikilink: {path.relative_to(root).as_posix()} -> {target}"
                )
        rel = path.relative_to(root).as_posix()
        source_links = [link for link in links if "sources/" in link.replace("\\", "/")]
        if "/indexes/" in f"/{rel}" and len(source_links) > 200:
            errors.append(f"pagination exceeds 200 links: {rel} ({len(source_links)})")
        if graph.GRAPH_BEGIN in text and not rel.startswith("wiki/sources/"):
            managed_hubs.add(rel)
        if rel.startswith("wiki/sources/"):
            fm = _frontmatter(text)
            if graph.GRAPH_BEGIN in text:
                if fm.get("verification") != "unverified":
                    errors.append(f"graph-managed source is not unverified: {rel}")
                if fm.get("enrichment_state") != "graph-reviewed":
                    errors.append(f"graph-managed source lacks enrichment_state: {rel}")
            summary_hash = fm.get("summary_hash")
            generated_hash = fm.get("generated_summary_hash")
            if summary_hash and generated_hash and summary_hash != generated_hash:
                warnings.append(f"protected source summary changed: {rel}")
    for rel in sorted(managed_hubs):
        if incoming.get(rel, 0) == 0:
            errors.append(f"orphan graph hub: {rel}")

    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "counts": {
            "catalog": len(catalog_rows), "raw": len(raw_files),
            "sources": len(source_files), "connections": len(connections),
            "review_queue": len(queue), "managed_hubs": len(managed_hubs),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected", type=int)
    args = parser.parse_args()
    report = lint(args.root, args.expected)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
