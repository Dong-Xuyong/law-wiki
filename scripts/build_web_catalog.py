#!/usr/bin/env python3
"""Build deterministic, public web metadata from the Law Wiki."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def relative_pdf_path(root: Path, row: dict[str, Any]) -> str | None:
    value = str(row.get("pdf_path") or "")
    if value and (root / value).is_file():
        return value.replace("\\", "/")
    return None


def build_folder_tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: dict[str, Any] = {}
    for row in sorted(rows, key=lambda item: (str(item.get("folder", "")), str(item.get("title", "")))):
        parts = [part for part in str(row.get("folder") or "Sem pasta").replace("\\", "/").split("/") if part]
        cursor = roots
        for part in parts:
            node = cursor.setdefault(part, {"name": part, "count": 0, "children": {}})
            node["count"] += 1
            cursor = node["children"]

    def render(nodes: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "name": node["name"],
                "count": node["count"],
                "children": render(node["children"]),
            }
            for _, node in sorted(nodes.items(), key=lambda item: item[0].casefold())
        ]

    return render(roots)


def graph_payload(rows: list[dict[str, Any]], connections: list[dict[str, Any]]) -> dict[str, Any]:
    known = {str(row["id"]): row for row in rows}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    keywords: dict[str, dict[str, Any]] = {}
    keyword_documents: dict[str, set[str]] = defaultdict(set)
    keyword_nodes: dict[str, set[str]] = defaultdict(set)

    def add_node(key: str, label: str, node_type: str, document_id: str = "") -> None:
        nodes.setdefault(
            key,
            {"id": key, "label": label or key, "type": node_type, "documentId": document_id},
        )

    def add_keyword(
        key: str, label: str, keyword_type: str, document_id: str, node_id: str = ""
    ) -> None:
        keywords.setdefault(key, {"key": key, "label": label, "type": keyword_type})
        keyword_documents[key].add(document_id)
        if node_id:
            keyword_nodes[key].add(node_id)

    for row in rows:
        document_id = str(row["id"])
        for kind, value in (
            ("website", row.get("website")),
            ("topic", row.get("topic_raw") or row.get("topic")),
            ("folder", row.get("folder")),
        ):
            label = str(value or "unknown")
            key = f"{kind}:{label.casefold()}"
            add_node(key, label, kind)
            edges.append({"source": key, "target": f"document:{document_id}", "predicate": kind})
            if kind == "topic":
                add_keyword(key, label, "topic", document_id, key)
        for category in row.get("categories") or []:
            label = str(category).replace("-", " ").strip().title()
            key = f"category:{str(category).casefold()}"
            add_keyword(key, label, "category", document_id)

    for item in connections:
        if item.get("review_status") != "accepted":
            continue
        document_id = str(item.get("source_document_id", ""))
        if document_id not in known:
            continue
        subject = f"document:{document_id}"
        add_node(subject, str(known[document_id].get("title") or known[document_id].get("filename")), "document", document_id)
        obj = item.get("object") or {}
        object_key = str(obj.get("key", ""))
        if not object_key:
            continue
        target = object_key if object_key.startswith("document:") else object_key
        target_document = target.removeprefix("document:") if target.startswith("document:") else ""
        object_label = str(obj.get("label") or target)
        object_type = str(obj.get("type") or "concept")
        add_node(target, object_label, object_type, target_document)
        edges.append({"source": subject, "target": target, "predicate": str(item.get("predicate") or "related")})
        if object_type in {"concept", "instrument"}:
            add_keyword(target, object_label, object_type, document_id, target)

    # Give the initial non-document view a real mind-map hierarchy.
    add_node("root:law-wiki", "Law Wiki", "root")
    visible_types = {"website", "topic", "folder", "instrument", "case"}
    group_labels = {
        "website": "Fontes", "topic": "Temas", "folder": "Pastas",
        "instrument": "Legislação", "case": "Processos",
    }
    for node_type, label in group_labels.items():
        group_key = f"group:{node_type}"
        add_node(group_key, label, "group")
        edges.append({"source": "root:law-wiki", "target": group_key, "predicate": "contains"})
    for node in list(nodes.values()):
        if node["type"] not in visible_types:
            continue
        group_key = f"group:{node['type']}"
        edges.append({"source": group_key, "target": node["id"], "predicate": "contains"})

    # Metadata document nodes are created only when their hub is expanded in the UI.
    compact_nodes = [node for node in nodes.values() if node["type"] != "document" or node["id"] in {
        edge["source"] for edge in edges if edge["predicate"] not in {"website", "topic", "folder"}
    }]
    unique_edges = {
        (edge["source"], edge["predicate"], edge["target"]): edge
        for edge in edges
    }
    rendered_edges = list(unique_edges.values())
    document_neighbors: dict[str, set[str]] = defaultdict(set)
    child_neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in rendered_edges:
        if edge["target"].startswith("document:"):
            document_neighbors[edge["source"]].add(edge["target"])
        if edge["source"].startswith("document:"):
            document_neighbors[edge["target"]].add(edge["source"])
        if edge["predicate"] == "contains":
            child_neighbors[edge["source"]].add(edge["target"])
    for node in compact_nodes:
        if node["id"] == "root:law-wiki":
            node["count"] = len(rows)
        elif node["type"] == "group":
            node["count"] = len(child_neighbors[node["id"]])
        else:
            node["count"] = len(document_neighbors[node["id"]])
    rendered_keywords = []
    for key, keyword in keywords.items():
        rendered_keywords.append({
            **keyword,
            "count": len(keyword_documents[key]),
            "documents": sorted(keyword_documents[key]),
            "nodeIds": sorted(keyword_nodes[key]),
        })
    rendered_keywords.sort(key=lambda item: (-item["count"], item["label"].casefold(), item["key"]))
    return {"nodes": compact_nodes, "edges": rendered_edges, "keywords": rendered_keywords}


def build(root: Path, generated: Path, public_data: Path) -> dict[str, int]:
    base = load_jsonl(root / "data" / "catalog.jsonl")
    pdf = load_jsonl(root / "data" / "pdf-catalog.jsonl")
    rows_by_id = {str(row["id"]): row for row in [*base, *pdf]}
    rows = []
    for row in rows_by_id.values():
        public = {
            key: row.get(key)
            for key in (
                "id", "title", "filename", "folder", "year", "website", "topic",
                "topic_raw", "topic_kind", "sector", "sectors", "categories",
                "document_type", "rel_raw", "rel_source", "verification",
                "content_hash", "text_chars", "summary_chars",
            )
        }
        public["pdf_path"] = relative_pdf_path(root, row)
        rows.append(public)
    rows.sort(key=lambda item: (str(item.get("title", "")).casefold(), str(item["id"])))

    catalog = {"generatedFrom": "Law Wiki", "count": len(rows), "documents": rows}
    folders = build_folder_tree(rows)
    graph = graph_payload(rows, load_jsonl(root / "data" / "connections.jsonl"))
    for target in (generated, public_data):
        write_json(target / "catalog.json", catalog)
        write_json(target / "folders.json", folders)
        write_json(target / "graph.json", graph)

    pdf_output = public_data.parent / "pdfs"
    if pdf_output.exists():
        shutil.rmtree(pdf_output)
    copied = 0
    for row in rows:
        rel = row.get("pdf_path")
        if not rel:
            continue
        source = root / str(rel)
        destination = pdf_output / source.relative_to(root / "raw" / "pdfs")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return {"documents": len(rows), "graph_nodes": len(graph["nodes"]), "pdfs": copied}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--generated", type=Path)
    parser.add_argument("--public-data", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    generated = args.generated or root / "site" / "src" / "generated"
    public_data = args.public_data or root / "site" / "public" / "data"
    result = build(root, generated, public_data)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
