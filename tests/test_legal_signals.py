import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import extract_legal_signals as signals  # noqa: E402
import select_pilot  # noqa: E402


BODY = (
    "Tribunal da Relação de Lisboa\r\n"
    "Processo n.º 1234/22.1T8LSB\r"
    "ECLI:PT:TRL:2023:1234.22.1T8LSB.A\r\n"
    "SENTENÇA\r\n"
    "Reclamante: Ana; Reclamada: Loja, Lda.\r\n"
    "Direito aplicável: artigo 12.º, n.º 1 da Lei n.º 24/96 e "
    "art. 562.º do Código Civil.\r\n"
    "Lisboa, 7 de março de 2023\r\n"
    "DECISÃO:\r\n"
    "Nestes termos, julga-se procedente o pedido.\r\n"
)


def raw(body=BODY):
    return "---\r\nid: x\r\n---\r\n\r\n# Title\r\n\r\n## Full text\r\n\r\n" + body


def record(doc_id, website="A", topic="T1", year="2020", **extra):
    result = {
        "id": doc_id,
        "website": website,
        "topic": topic,
        "year": year,
        "filename": f"Sentença {doc_id}.pdf",
        "folder": "Jurisprudencia",
        "content_hash": hashlib.sha256(doc_id.encode()).hexdigest(),
        "text_chars": 5000,
        "short_text": False,
    }
    result.update(extra)
    return result


class PayloadAndExtractionTests(unittest.TestCase):
    def test_payload_normalization_and_offset_contract(self):
        payload = signals.parse_full_text(raw())
        self.assertNotIn("\r", payload)
        self.assertTrue(payload.startswith("Tribunal da Relação"))
        result = signals.extract_signals(payload, {"id": "x", "content_hash": "abc"})
        self.assertEqual(
            result["offset_contract"],
            "python-unicode-code-point-half-open; normalized-full-text-payload",
        )
        for collection in (
            "document_types",
            "forums",
            "process_numbers",
            "dates",
            "ecli",
            "citations",
            "dispositions",
        ):
            self.assertTrue(result[collection], collection)
            for candidate in result[collection]:
                span = candidate["provenance"]
                self.assertEqual(payload[span["start"] : span["end"]], span["quote"])
                self.assertEqual(
                    hashlib.sha256(span["quote"].encode()).hexdigest(), span["sha256"]
                )
                self.assertEqual(candidate["extractor_version"], signals.EXTRACTOR_VERSION)

    def test_missing_full_text_heading_fails(self):
        with self.assertRaisesRegex(ValueError, "Full text"):
            signals.parse_full_text("# not a raw document")

    def test_last_disposition_is_used_and_bounded(self):
        payload = "DECISÃO:\nold\n" + ("x" * 6000) + "\nDECISÃO:\nfinal"
        disposition = signals.extract_signals(payload)["dispositions"][0]
        self.assertEqual(disposition["value"], "DECISÃO:\nfinal")
        self.assertLessEqual(len(disposition["value"]), 5000)

    def test_exact_and_conservative_families(self):
        rows = [
            record("a", filename="Caso (cópia).pdf", content_hash="same"),
            record("b", filename="Caso.pdf", content_hash="same"),
            record("c", filename="Other.pdf", content_hash="different"),
        ]
        exact = signals.exact_duplicate_groups(rows)
        self.assertEqual(exact[0]["ids"], ["a", "b"])
        families = signals.conservative_families(
            rows, {"a": "A " * 60, "b": "a\n" * 60, "c": "different " * 20}
        )
        self.assertTrue(any(item["kind"] == "filename" for item in families))
        self.assertTrue(any(item["kind"] == "normalized-content" for item in families))

    def test_packets_are_bounded_and_neighbors_deterministic(self):
        rows = [record("a"), record("b"), record("c"), record("d")]
        payloads = {
            "a": "alpha uniqueterm shared legal words",
            "b": "beta uniqueterm shared legal words",
            "c": "gamma separate doctrine",
            "d": "delta other material",
        }
        first = signals.lexical_neighbors(rows, payloads)
        second = signals.lexical_neighbors(list(reversed(rows)), payloads)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["a"]), 3)
        extracted = signals.extract_signals(signals.parse_full_text(raw()))
        packet = signals.build_packet(rows[0], signals.parse_full_text(raw()), extracted, first["a"], 200)
        self.assertLessEqual(len(packet["neighbor_candidates"]), 3)
        for windows in packet["windows"].values():
            for window in windows:
                self.assertLessEqual(len(window["quote"]), 200)


class PilotSelectionTests(unittest.TestCase):
    def diverse_records(self):
        return [
            record("short", short_text=True, text_chars=5, website="A", topic="T1", year="2020"),
            record("supplied", website="Fornecidos", topic="Documentos fornecidos", year="2021"),
            record("law", website="B", topic="Legislacao", year="2022"),
            record("ocr", website="C", topic="T2", year="2023", ocr_poor=True),
            record("ordinary", website="D", topic="T3", year="2024"),
            record("dup1", website="A", topic="T4", year="2020", content_hash="duplicate"),
            record("dup2", website="B", topic="T4", year="2021", content_hash="duplicate"),
            record("conflict1", process_keys=["123x"], content_hash="one"),
            record("conflict2", process_keys=["123x"], content_hash="two"),
        ]

    def test_selection_covers_risks_dimensions_and_duplicates(self):
        rows = self.diverse_records()
        chosen = select_pilot.choose_pilot(rows, count=len(rows), seed=7)
        self.assertEqual({row["id"] for row in chosen}, {row["id"] for row in rows})
        select_pilot.validate_selection(rows, chosen)
        short = next(row for row in chosen if row["id"] == "short")
        self.assertIn("all-short-text-records", short["selection_reasons"])

    def test_selection_is_deterministic(self):
        rows = self.diverse_records()
        one = select_pilot.choose_pilot(rows, count=len(rows), seed=7)
        two = select_pilot.choose_pilot(list(reversed(rows)), count=len(rows), seed=7)
        self.assertEqual([row["id"] for row in one], [row["id"] for row in two])

    def test_impossible_coverage_fails(self):
        rows = [
            record("a", website="A", topic="T1", year="2020"),
            record("b", website="B", topic="T2", year="2021"),
        ]
        with self.assertRaisesRegex(ValueError, "coverage impossible"):
            select_pilot.choose_pilot(rows, count=1)


class ExtractorCliTests(unittest.TestCase):
    def test_cli_writes_only_requested_enrichment_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_path = root / "raw" / "documents" / "x" / "2023" / "x.md"
            raw_path.parent.mkdir(parents=True)
            raw_text = raw()
            raw_path.write_text(raw_text, encoding="utf-8", newline="")
            payload = signals.parse_full_text(raw_text)
            catalog = root / "data" / "catalog.jsonl"
            catalog.parent.mkdir()
            row = record("x", content_hash=hashlib.sha256(payload.encode()).hexdigest())
            row["rel_raw"] = str(raw_path.relative_to(root)).replace("\\", "/")
            catalog.write_text(json.dumps(row) + "\n", encoding="utf-8")
            manifest = root / "data" / "pilot.jsonl"
            manifest.write_text(json.dumps({"id": "x"}) + "\n", encoding="utf-8")
            output = root / "data" / "enrichment-test"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "extract_legal_signals.py"),
                    "--root",
                    str(root),
                    "--output-dir",
                    str(output),
                    "--manifest",
                    str(manifest),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"legal-signals.jsonl", "review-packets.jsonl", "document-families.json"},
            )
            self.assertEqual(raw_path.read_text(encoding="utf-8"), raw_text.replace("\r\n", "\n").replace("\r", "\n"))


if __name__ == "__main__":
    unittest.main()
