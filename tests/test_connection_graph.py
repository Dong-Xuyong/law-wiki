import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_connection_graph as graph  # noqa: E402


DOC_A = "law_1111111111111111"
DOC_B = "law_2222222222222222"


class ConnectionGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        body = "Água e Lei n.º 12/2020."
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        rows = []
        for doc_id, name in ((DOC_A, "a"), (DOC_B, "b")):
            raw = f"raw/documents/site/2020/{doc_id}.md"
            source = f"wiki/sources/{name}--{doc_id}.md"
            (self.root / raw).parent.mkdir(parents=True, exist_ok=True)
            (self.root / raw).write_text(
                f"---\nid: {doc_id}\n---\n\n# {name}\n\n## Full text\n\n{body}\n",
                encoding="utf-8",
            )
            (self.root / source).parent.mkdir(parents=True, exist_ok=True)
            (self.root / source).write_text(
                "---\nverification: unverified\n---\n\n# Source\n\n## Summary\n\nKEEP THIS SUMMARY\n",
                encoding="utf-8",
            )
            rows.append({
                "id": doc_id, "rel_raw": raw, "rel_source": source,
                "content_hash": content_hash, "filename": name + ".pdf",
                "website": "Site", "folder": "F", "year": "2020",
                "topic": "Água", "csv_row": 1 if doc_id == DOC_A else 2,
            })
        (self.root / "data").mkdir(exist_ok=True)
        self._write_jsonl(self.root / "data/catalog.jsonl", rows)
        self.body = body

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def raw_assertion(self, method: str = "grok-4.6", confidence: float = 0.96) -> dict:
        quote = "Lei n.º 12/2020"
        start = self.body.index(quote)
        assertion = {
            "subject": {"key": f"document:{DOC_A}", "type": "document", "label": "A"},
            "predicate": "cites_instrument",
            "object": {"key": "instrument:pt:lei:12/2020", "type": "instrument", "label": "Lei 12/2020"},
            "source_document_id": DOC_A,
            "provenance": {
                "kind": "raw-span",
                "raw_path": f"raw/documents/site/2020/{DOC_A}.md",
                "section": "applicable-law", "start": start, "end": start + len(quote),
                "quote": quote, "evidence_hash": graph.sha256_text(quote),
            },
            "method": method, "extractor_version": "test", "confidence": confidence,
            "review_status": "candidate",
        }
        assertion["assertion_id"] = graph.compute_assertion_id(assertion)
        return assertion

    def test_normalized_payload_coordinates_and_hash(self) -> None:
        markdown = "---\r\nid: x\r\n---\r\n\r\n## Full text\r\n\r\nA\r\nB\r\n"
        self.assertEqual(graph.full_text_payload(markdown), "A\nB")
        assertion = self.raw_assertion()
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        graph.validate_provenance(assertion, self.root, catalog)

    def test_invalid_span_and_assertion_id_are_rejected(self) -> None:
        assertion = self.raw_assertion()
        assertion["provenance"]["start"] += 1
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        with self.assertRaises(graph.ContractError):
            graph.validate_provenance(assertion, self.root, catalog)
        assertion = self.raw_assertion()
        assertion["assertion_id"] = "conn_" + "0" * 24
        with self.assertRaises(graph.ContractError):
            graph.adjudicate([assertion], [], [], self.root, catalog)

    def test_grok_requires_two_reviews_and_confidence(self) -> None:
        assertion = self.raw_assertion()
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        review = [{"assertion_id": assertion["assertion_id"], "decision": "accepted"}]
        accepted, queue = graph.adjudicate([assertion], review, review, self.root, catalog)
        self.assertEqual(len(accepted), 1)
        self.assertFalse(queue)
        low = self.raw_assertion(confidence=0.5)
        low_review = [{"assertion_id": low["assertion_id"], "decision": "accepted"}]
        accepted, queue = graph.adjudicate([low], low_review, low_review, self.root, catalog)
        self.assertFalse(accepted)
        self.assertIn("low-confidence", queue[0]["reason"])

    def test_reviewer_wrappers_and_resolver_conflicts_queue(self) -> None:
        first = self.raw_assertion()
        first["predicate"] = "decided_by"
        first["object"] = {"key": "entity:court-a", "type": "forum", "label": "Court A"}
        first["assertion_id"] = graph.compute_assertion_id(first)
        second = dict(first)
        second["object"] = {"key": "entity:court-b", "type": "forum", "label": "Court B"}
        second["assertion_id"] = graph.compute_assertion_id(second)
        reviews_a = [{"reviews": [
            {"assertion_id": first["assertion_id"], "decision": "accepted"},
            {"assertion_id": second["assertion_id"], "decision": "accepted"},
        ]}]
        reviews_b = [{"assertions": [
            {"assertion_id": first["assertion_id"], "review_status": "accepted"},
            {"assertion_id": second["assertion_id"], "review_status": "accepted"},
        ]}]
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        accepted, queue = graph.adjudicate(
            [first, second], reviews_a, reviews_b, self.root, catalog
        )
        self.assertFalse(accepted)
        self.assertTrue(all("resolver-conflict" in item["reason"] for item in queue))

    def test_case_and_forum_edges_require_direct_combined_support(self) -> None:
        assertion = self.raw_assertion()
        assertion["predicate"] = "document_of"
        assertion["object"] = {
            "key": "case:pt:cniacc:12/2020",
            "type": "case",
            "label": "CNIACC 12/2020",
        }
        assertion["assertion_id"] = graph.compute_assertion_id(assertion)
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        review = [{"assertion_id": assertion["assertion_id"], "decision": "accepted"}]
        accepted, queue = graph.adjudicate(
            [assertion], review, review, self.root, catalog
        )
        self.assertFalse(accepted)
        self.assertEqual(queue[0]["review_status"], "rejected")
        self.assertIn("direct-support", queue[0]["reason"])

    def test_valid_content_hash_edge_is_deterministically_accepted(self) -> None:
        content_hash = hashlib.sha256(self.body.encode()).hexdigest()
        assertion = {
            "subject": {"key": f"document:{DOC_A}", "type": "document", "label": "A"},
            "predicate": "exact_duplicate_of",
            "object": {"key": f"document:{DOC_B}", "type": "document", "label": "B"},
            "source_document_id": DOC_A,
            "provenance": {"kind": "content-hash", "content_hash": content_hash, "peer_document_id": DOC_B},
            "method": "content-hash", "extractor_version": "test", "confidence": 1.0,
            "review_status": "candidate", "reason": "identical full-text content hash",
        }
        assertion["assertion_id"] = graph.compute_assertion_id(assertion)
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        accepted, queue = graph.adjudicate([assertion], [], [], self.root, catalog)
        self.assertEqual([assertion["assertion_id"]], [accepted[0]["assertion_id"]])
        self.assertFalse(queue)

    def test_materialization_preserves_summary_and_is_idempotent(self) -> None:
        assertion = self.raw_assertion()
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        review = [{"assertion_id": assertion["assertion_id"], "decision": "accepted"}]
        accepted, queue = graph.adjudicate([assertion], review, review, self.root, catalog)
        graph.materialize(self.root, self.root, accepted, queue, catalog)
        source = self.root / catalog[DOC_A]["rel_source"]
        first = source.read_text(encoding="utf-8")
        self.assertIn("KEEP THIS SUMMARY", first)
        self.assertIn("enrichment_state: graph-reviewed", first)
        self.assertEqual(first.count("enrichment_state:"), 1)
        self.assertIn(graph.GRAPH_BEGIN, first)
        graph.materialize(self.root, self.root, accepted, queue, catalog)
        self.assertEqual(first, source.read_text(encoding="utf-8"))
        hub = self.root / graph.canonical_node_path(assertion["object"])
        self.assertTrue(hub.is_file())

    def test_dry_run_reports_without_writing(self) -> None:
        assertion = self.raw_assertion()
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        review = [{"assertion_id": assertion["assertion_id"], "decision": "accepted"}]
        accepted, queue = graph.adjudicate([assertion], review, review, self.root, catalog)
        report = graph.materialize(self.root, self.root, accepted, queue, catalog, dry_run=True)
        self.assertEqual(report["accepted"], 1)
        self.assertFalse((self.root / "data/connections.jsonl").exists())
        self.assertNotIn(graph.GRAPH_BEGIN, (self.root / catalog[DOC_A]["rel_source"]).read_text())

    def test_canonical_paths_and_lateral_cap(self) -> None:
        self.assertEqual(
            graph.canonical_node_path({"key": "case:pt:lisboa:1/20", "type": "case", "label": "Case"}),
            "wiki/cases/pt-lisboa-1-20.md",
        )
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        base = self.raw_assertion()
        lateral = []
        for number in range(5):
            edge = dict(base)
            edge["predicate"] = "semantically_similar_to"
            edge["object"] = {"key": f"document:{DOC_B}", "type": "document", "label": f"Peer {number}"}
            edge["reason"] = f"shared concrete term {number}"
            lateral.append(edge)
        rendered = graph.render_source(
            (self.root / catalog[DOC_A]["rel_source"]).read_text(encoding="utf-8"),
            lateral, catalog,
        )
        self.assertEqual(rendered.count("shared concrete term"), 3)

    def test_remove_managed_block(self) -> None:
        text = f"# Keep\n\n{graph.GRAPH_BEGIN}\nremove\n{graph.GRAPH_END}\n\nTail\n"
        cleaned = graph.remove_managed(text, graph.GRAPH_BEGIN, graph.GRAPH_END)
        self.assertIn("# Keep", cleaned)
        self.assertIn("Tail", cleaned)
        self.assertNotIn(graph.GRAPH_BEGIN, cleaned)


if __name__ == "__main__":
    unittest.main()
