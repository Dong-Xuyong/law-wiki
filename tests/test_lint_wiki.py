import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_connection_graph as graph  # noqa: E402
import lint_wiki  # noqa: E402


DOC = "law_aaaaaaaaaaaaaaaa"


class LintWikiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        body = "Consumer text"
        self.record = {
            "id": DOC, "rel_raw": f"raw/documents/x/2024/{DOC}.md",
            "rel_source": f"wiki/sources/doc--{DOC}.md",
            "content_hash": hashlib.sha256(body.encode()).hexdigest(),
            "filename": "Doc.pdf", "website": "X", "folder": "F",
            "year": "2024", "topic": "Consumer", "csv_row": 1,
        }
        raw = self.root / self.record["rel_raw"]
        raw.parent.mkdir(parents=True)
        raw.write_text(f"---\nid: {DOC}\n---\n\n## Full text\n\n{body}\n", encoding="utf-8")
        source = self.root / self.record["rel_source"]
        source.parent.mkdir(parents=True)
        source.write_text("---\nverification: unverified\n---\n\n# Doc\n", encoding="utf-8")
        (self.root / "data").mkdir()
        self.write_jsonl(self.root / "data/catalog.jsonl", [self.record])

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def write_jsonl(path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def metadata_edge(self) -> dict:
        value = self.record["topic"]
        edge = {
            "subject": {"key": f"document:{DOC}", "type": "document", "label": "Doc"},
            "predicate": "about_topic",
            "object": {"key": "topic:consumer", "type": "topic", "label": value},
            "source_document_id": DOC,
            "provenance": {
                "kind": "metadata-field", "field": "topic", "value": value,
                "evidence_hash": graph.sha256_text(value),
            },
            "method": "metadata", "extractor_version": "test",
            "confidence": 1.0, "review_status": "accepted",
        }
        edge["assertion_id"] = graph.compute_assertion_id(edge)
        return edge

    def materialize_clean_graph(self) -> None:
        edge = self.metadata_edge()
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        graph.materialize(self.root, self.root, [edge], [], catalog)

    def test_clean_materialized_fixture_passes(self) -> None:
        self.materialize_clean_graph()
        report = lint_wiki.lint(self.root, expected=1)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["counts"]["connections"], 1)

    def test_raw_source_catalog_parity(self) -> None:
        (self.root / self.record["rel_source"]).unlink()
        report = lint_wiki.lint(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("source/catalog parity" in error for error in report["errors"]))
        self.assertTrue(any("missing rel_source" in error for error in report["errors"]))

    def test_invalid_evidence_is_reported(self) -> None:
        edge = self.metadata_edge()
        edge["provenance"]["evidence_hash"] = "0" * 64
        self.write_jsonl(self.root / "data/connections.jsonl", [edge])
        report = lint_wiki.lint(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("evidence hash mismatch" in error for error in report["errors"]))

    def test_marker_balance_and_review_state(self) -> None:
        source = self.root / self.record["rel_source"]
        source.write_text(
            source.read_text(encoding="utf-8") + graph.GRAPH_BEGIN + "\n",
            encoding="utf-8",
        )
        queued = self.metadata_edge()
        self.write_jsonl(self.root / "data/enrichment/review-queue.jsonl", [queued])
        report = lint_wiki.lint(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("marker imbalance" in error for error in report["errors"]))
        self.assertTrue(any("accepted edge left" in error for error in report["errors"]))

    def test_pagination_limit_and_broken_targets(self) -> None:
        index = self.root / "wiki/indexes/by-topic/consumer.md"
        index.parent.mkdir(parents=True)
        links = "\n".join(f"- [[sources/missing-{n}]]" for n in range(201))
        index.write_text(f"# Consumer\n\n{links}\n", encoding="utf-8")
        report = lint_wiki.lint(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("pagination exceeds 200" in error for error in report["errors"]))
        self.assertTrue(any("broken wikilink" in error for error in report["errors"]))

    def test_orphan_hub_and_verification_state(self) -> None:
        hub = self.root / "wiki/concepts/orphan.md"
        hub.parent.mkdir(parents=True)
        hub.write_text(
            "---\nverification: verified\n---\n\n"
            f"{graph.GRAPH_BEGIN}\n# Orphan\n{graph.GRAPH_END}\n",
            encoding="utf-8",
        )
        report = lint_wiki.lint(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("orphan graph hub" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
