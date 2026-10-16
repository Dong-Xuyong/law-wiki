import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_connection_graph as graph  # noqa: E402
import extract_legal_signals as signals  # noqa: E402
import graph_tranche  # noqa: E402


def catalog_row(number: int, **extra) -> dict:
    doc_id = f"law_{number:016x}"
    row = {
        "id": doc_id,
        "folder": "F",
        "filename": f"{number}.pdf",
        "year": "2024",
        "website": "CICAP",
        "topic": "Outros",
        "tokens": 10,
        "tokens_sm": 10,
        "content_hash": f"{number:064x}",
        "rel_raw": f"raw/documents/cicap/2024/{doc_id}.md",
        "rel_source": f"wiki/sources/{number}--{doc_id}.md",
        "source_slug": f"{number}--{doc_id}",
        "text_chars": 1000,
        "summary_chars": 20,
        "short_text": False,
        "website_slug": "cicap",
        "topic_slug": "outros",
    }
    row.update(extra)
    return row


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class TrancheSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rows = [catalog_row(number) for number in range(8)]
        write_jsonl(self.root / "data/catalog.jsonl", self.rows)
        write_jsonl(
            self.root / "data/enrichment/pilot-manifest.jsonl",
            [{"id": self.rows[0]["id"]}, {"id": self.rows[1]["id"]}],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_select_is_deterministic_idempotent_and_excludes_pilot(self) -> None:
        first = graph_tranche.select_tranche(self.root, 3, 7)
        second = graph_tranche.select_tranche(self.root, 3, 7)
        self.assertEqual(first["tranche"], "t001")
        self.assertEqual(second["tranche"], "t001")
        manifest = graph.load_jsonl(self.root / "data/enrichment/tranches/t001/manifest.jsonl")
        ids = [row["id"] for row in manifest]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)
        pilot = {self.rows[0]["id"], self.rows[1]["id"]}
        self.assertTrue(pilot.isdisjoint(ids))
        again = graph.load_jsonl(self.root / "data/enrichment/tranches/t001/manifest.jsonl")
        self.assertEqual(ids, [row["id"] for row in again])
        extractor = self.root / "data/enrichment/tranches/t001/extractor-01.jsonl"
        extractor.write_text("", encoding="utf-8")
        third = graph_tranche.select_tranche(self.root, 3, 7)
        self.assertEqual(third["tranche"], "t002")
        later = [row["id"] for row in graph.load_jsonl(
            self.root / "data/enrichment/tranches/t002/manifest.jsonl"
        )]
        self.assertEqual(len(later), 3)
        self.assertTrue(set(later).isdisjoint(ids))
        self.assertTrue(set(later).isdisjoint(pilot))


class PacketAndDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.body = (
            "Processo nº 520/2024\n"
            "TRIBUNAL ARBITRAL DE CONSUMO\n"
            "CICAP\n"
            "Lei n.º 24/96, de 31 de julho\n"
            "artigo 12.º da Lei n.º 24/96\n"
            "Reclamada: Oficina do Relógio, Lda.\n"
            "Julga-se totalmente improcedente a ação.\n"
            "Aplica-se o Decreto-\nLei n.º 84/2021.\n"
        )
        self.record = catalog_row(4, content_hash=hashlib.sha256(self.body.encode()).hexdigest())
        raw = self.root / self.record["rel_raw"]
        raw.parent.mkdir(parents=True)
        raw.write_text(
            f"---\nid: {self.record['id']}\n---\n\n## Full text\n\n{self.body}\n",
            encoding="utf-8",
        )
        source = self.root / self.record["rel_source"]
        source.parent.mkdir(parents=True)
        source.write_text("---\nverification: unverified\n---\n\n# Source\n", encoding="utf-8")
        write_jsonl(self.root / "data/catalog.jsonl", [self.record])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_packets_split_on_batch_size(self) -> None:
        graph_tranche.select_tranche(self.root, 1, 3)
        reports = graph_tranche.write_packets(self.root, "t001", batch_size=1)
        self.assertEqual(reports[0]["packets"], 1)
        directory = self.root / "data/enrichment/tranches/t001"
        self.assertEqual(len(graph.load_jsonl(directory / "packets.jsonl")), 1)
        self.assertTrue((directory / "packets-01.jsonl").is_file())
        first = (directory / "packets.jsonl").read_text(encoding="utf-8")
        graph_tranche.write_packets(self.root, "t001", batch_size=1)
        self.assertEqual(first, (directory / "packets.jsonl").read_text(encoding="utf-8"))

    def test_draft_spans_come_from_windows(self) -> None:
        payload = signals.parse_full_text((self.root / self.record["rel_raw"]).read_text(encoding="utf-8"))
        extracted = signals.extract_signals(payload, self.record)
        packet = signals.build_packet(self.record, payload, extracted, [])
        row = graph_tranche.draft_document_row(self.record, payload, packet, [], "01")
        by_predicate = {}
        catalog, _ = graph.load_catalog(self.root / "data/catalog.jsonl")
        for assertion in row["assertions"]:
            by_predicate.setdefault(assertion["predicate"], assertion)
            graph.validate_provenance(assertion, self.root, catalog)
            provenance = assertion["provenance"]
            if provenance["kind"] != "raw-span":
                continue
            self.assertEqual(payload[provenance["start"] : provenance["end"]], provenance["quote"])
            self.assertTrue(graph_tranche._inside_window(provenance["start"], provenance["end"], packet))
        self.assertEqual(by_predicate["decided_by"]["object"]["key"], "forum:pt:cicap")
        self.assertEqual(by_predicate["document_of"]["object"]["key"], "case:pt:cicap:520/2024")
        self.assertEqual(by_predicate["has_outcome"]["object"]["key"], "outcome:improcedente")
        self.assertEqual(by_predicate["cites_instrument"]["object"]["key"], "instrument:pt:lei:24/96")
        decree = [
            assertion for assertion in row["assertions"]
            if assertion["object"]["key"] == "instrument:pt:decreto-lei:84/2021"
        ]
        self.assertEqual(len(decree), 1)
        self.assertIn("Decreto-", decree[0]["provenance"]["quote"])
        self.assertEqual(by_predicate["cites_provision"]["object"]["key"], "provision:pt:lei:24/96:art.12")
        self.assertEqual(by_predicate["published_by"]["provenance"]["kind"], "metadata-field")
        self.assertLessEqual(
            sum(assertion["predicate"] in graph.LATERAL_PREDICATES for assertion in row["assertions"]),
            3,
        )

    def test_check_rejects_a_span_outside_the_packet_window(self) -> None:
        payload = signals.parse_full_text((self.root / self.record["rel_raw"]).read_text(encoding="utf-8"))
        extracted = signals.extract_signals(payload, self.record)
        packet = signals.build_packet(self.record, payload, extracted, [])
        graph_tranche.select_tranche(self.root, 1, 3)
        directory = self.root / "data/enrichment/tranches/t001"
        graph_tranche.write_jsonl(directory / "packets.jsonl", [packet], sort_keys=True)
        graph_tranche.write_jsonl(directory / "packets-01.jsonl", [packet], sort_keys=True)
        quote = "Lei n.º 24/96"
        start = payload.index(quote)
        # Shrink the stored window so the real quote falls outside it.
        packet["windows"]["header"] = [{
            "start": 0,
            "end": 5,
            "quote": payload[:5],
            "sha256": "0" * 64,
            "evidence_hash": "0" * 64,
        }]
        for name in ("party", "applicable_law", "citation", "disposition"):
            packet["windows"][name] = []
        graph_tranche.write_jsonl(directory / "packets.jsonl", [packet], sort_keys=True)
        graph_tranche.write_jsonl(directory / "packets-01.jsonl", [packet], sort_keys=True)
        assertion = graph_tranche._raw(
            self.record, "cites_instrument",
            graph_tranche._object("instrument:pt:lei:24/96", "instrument", quote),
            payload, start, start + len(quote), "header", "Outside the window.", 0.96,
        )
        graph_tranche.write_jsonl(directory / "extractor-01.jsonl", [{
            "document_id": self.record["id"],
            "batch": "01",
            "assertions": [assertion],
        }])
        report = graph_tranche.check_tranche(self.root, "t001")
        self.assertFalse(report["ok"])
        self.assertTrue(any("outside packet windows" in error for error in report["errors"]))


class BuildPreservationTests(unittest.TestCase):
    def test_build_keeps_pilot_metadata_and_queues_unreviewed_spans(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        body = "Lei n.º 24/96 aplica-se."
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        pilot = catalog_row(1, content_hash=content_hash, filename="Pilot.pdf")
        tranche = catalog_row(2, content_hash=hashlib.sha256(b"other").hexdigest(), filename="Tranche.pdf")
        for record, text in ((pilot, body), (tranche, body)):
            raw = root / record["rel_raw"]
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(f"---\nid: {record['id']}\n---\n\n## Full text\n\n{text}\n", encoding="utf-8")
            source = root / record["rel_source"]
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("---\nverification: unverified\n---\n\n# Source\n", encoding="utf-8")
        write_jsonl(root / "data/catalog.jsonl", [pilot, tranche])
        payload = signals.parse_full_text((root / pilot["rel_raw"]).read_text(encoding="utf-8"))
        quote = "Lei n.º 24/96"
        start = payload.index(quote)
        metadata = graph_tranche._metadata(
            pilot, "published_by",
            graph_tranche._object("organization:cicap", "organization", "CICAP"),
            "website", "CICAP", "Catalog website.",
        )
        queued = graph_tranche._raw(
            tranche, "cites_instrument",
            graph_tranche._object("instrument:pt:lei:24/96", "instrument", quote),
            payload, start, start + len(quote), "applicable-law", "Cites the statute.", 0.96,
        )
        pilot_dir = root / "data/enrichment/pilot"
        graph_tranche.write_jsonl(pilot_dir / "extractor-01.jsonl", [{
            "document_id": pilot["id"], "assertions": [metadata],
        }])
        graph_tranche.write_jsonl(pilot_dir / "reviewer-1.jsonl", [{
            "assertion_id": queued["assertion_id"], "decision": "rejected",
            "reason": "not this reviewer's document", "reviewer": "grok-reviewer-1",
        }])
        graph_tranche.write_jsonl(pilot_dir / "reviewer-2.jsonl", [{
            "assertion_id": queued["assertion_id"], "decision": "rejected",
            "reason": "not this reviewer's document", "reviewer": "grok-reviewer-2",
        }])
        tranche_dir = root / "data/enrichment/tranches/t001"
        graph_tranche.write_jsonl(tranche_dir / "extractor-01.jsonl", [{
            "document_id": tranche["id"], "assertions": [queued],
        }])
        report = graph_tranche.build_all(root)
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["queued"], 1)
        saved = (root / "data/connections.jsonl").read_text(encoding="utf-8")
        self.assertIn(metadata["assertion_id"], saved)
        self.assertNotIn(queued["assertion_id"], saved)
        graph_tranche.build_all(root)
        self.assertEqual(saved, (root / "data/connections.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
