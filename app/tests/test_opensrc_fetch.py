"""Offline tests for the open-source Regulation 261/2004 ingest."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_connection_graph  # noqa: E402
import import_csv  # noqa: E402
from app.ingest.sources import fetch_open_sources as opensrc  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opensrc"
CATALOG_FIELDS = (
    "id",
    "title",
    "filename",
    "folder",
    "year",
    "website",
    "topic",
    "topic_raw",
    "rel_raw",
    "rel_source",
    "verification",
    "content_hash",
    "text_chars",
    "document_type",
    "kind",
    "source_url",
)


class OpenSourceExtractionTests(unittest.TestCase):
    def test_html_to_text_keeps_paragraphs_and_drops_chrome(self) -> None:
        html = (FIXTURES / "eurlex-snippet.html").read_text(encoding="utf-8")
        text = opensrc.html_to_text(html)
        self.assertNotIn("Avis juridique", text)
        self.assertNotIn("ignored chrome", text)
        self.assertNotIn("do-not-keep", text)
        self.assertIn("32004R0261", text)
        self.assertIn("Regulamento (CE) n.° 261/2004 do Parlamento Europeu e do Conselho", text)
        self.assertIn("de 11 de Fevereiro de 2004", text)
        self.assertIn("Artigo 7.º\nDireito a indemnização", text)
        self.assertIn("\n\nRegulamento", text)

    def test_dgsi_extraction_keeps_court_fields_and_paragraphs(self) -> None:
        html = (FIXTURES / "dgsi-snippet.html").read_text(encoding="utf-8")
        extracted = opensrc.extract_dgsi(html, court="Supremo Tribunal de Justiça")
        self.assertEqual(extracted["process_number"], "123/20.0T8LSB.L1")
        self.assertEqual(extracted["relator"], "NOME RELATOR")
        self.assertEqual(extracted["decision_date"], "2024-01-15")
        self.assertEqual(extracted["year"], "2024")
        self.assertNotIn("Acórdãos STJ", extracted["text"])
        self.assertIn("Processo: 123/20.0T8LSB.L1", extracted["text"])
        self.assertIn("Relator: NOME RELATOR", extracted["text"])
        self.assertIn(
            "Acordam no Supremo Tribunal de Justiça.\n\nO Regulamento (CE) n.º 261/2004 aplica-se ao voo.",
            extracted["text"],
        )

    def test_dgsi_search_row_and_document_url(self) -> None:
        html = (FIXTURES / "dgsi-search-snippet.html").read_text(encoding="utf-8")
        hits = opensrc.parse_dgsi_search(html, website="DGSI-STJ", court="Supremo Tribunal de Justiça")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["process_number"], "6471/17.9T8BRG.G1.S1")
        self.assertEqual(hits[0]["relator"], "MARIA JOÃO VAZ TOMÉ")
        self.assertEqual(hits[0]["decision_date"], "2020-11-17")
        self.assertIn("TRANSPORTE AÉREO", hits[0]["descriptors"])
        url = opensrc.dgsi_document_url(hits[0]["href"])
        self.assertTrue(url.startswith("https://www.dgsi.pt/jstj.nsf/"))
        self.assertTrue(url.endswith("?OpenDocument"))
        self.assertNotIn("Highlight", url)

    def test_dgsi_hyphen_dates_are_day_month_year(self) -> None:
        self.assertEqual(opensrc.parse_dgsi_date("29-10-2020"), "2020-10-29")
        self.assertEqual(opensrc.parse_dgsi_date("09-02-2009"), "2009-02-09")
        self.assertEqual(opensrc.parse_dgsi_date("11/17/2020"), "2020-11-17")

    def test_cjeu_title_uses_case_line_when_judgment_opens_the_text(self) -> None:
        text = "\n".join([
            "ACÓRDÃO DO TRIBUNAL DE JUSTIÇA (Grande Secção)",
            "23 de outubro de 2012",
            "Nos processos apensos C-581/10 e C-629/10,",
            "que têm por objeto pedidos de decisão prejudicial",
            "Emeka Nelson,",
            "contra",
            "Deutsche Lufthansa AG",
        ])
        title = opensrc.eurlex_title(text, "62010CJ0581", "case_law")
        self.assertIn("C-581/10", title)
        self.assertIn("Emeka Nelson", title)

    def test_cellar_300_picks_portuguese_html(self) -> None:
        html = (FIXTURES / "cellar-300-snippet.html").read_text(encoding="utf-8")
        chosen = opensrc.choose_cellar_item(html)
        self.assertTrue(chosen.endswith("/DOC_3"))
        self.assertIn("texte_pt", html)


class _RecordFactory:
    def _sample(self, text: str = "Primeira versão do texto publicado.\n\nArtigo 7.º") -> dict:
        return opensrc.build_record(
            website="DGSI-STJ",
            folder="Fontes abertas/DGSI-STJ",
            filename="123/20.0T8LSB.L1",
            year="2024",
            kind="case_law",
            title="Supremo Tribunal de Justiça 123/20.0T8LSB.L1 (2024-01-15)",
            text=text,
            source_url="https://www.dgsi.pt/jstj.nsf/example?OpenDocument",
            process_number="123/20.0T8LSB.L1",
            relator="NOME RELATOR",
            decision_date="2024-01-15",
            court="Supremo Tribunal de Justiça",
        )


class OpenSourceIdentityTests(_RecordFactory, unittest.TestCase):
    def test_document_id_matches_importer(self) -> None:
        website = "EUR-Lex"
        folder = "Fontes abertas/EUR-Lex"
        filename = "CELEX-32004R0261"
        record = opensrc.build_record(
            website=website,
            folder=folder,
            filename=filename,
            year="2004",
            kind="legislation",
            title="Regulamento (CE) n.º 261/2004",
            text="Texto integral do regulamento.\n\nArtigo 7.º",
            source_url="https://publications.europa.eu/resource/celex/32004R0261",
            process_number="32004R0261",
            court="Jornal Oficial / EUR-Lex",
        )
        self.assertEqual(record["id"], import_csv.document_id(website, folder, filename))
        self.assertTrue(record["id"].startswith("law_"))
        self.assertEqual(len(record["id"]), 20)
        self.assertEqual(record["content_hash"], import_csv.content_hash(record["text"]))
        folded = opensrc.build_record(
            website=" eur-lex ",
            folder=folder,
            filename=filename,
            year="2004",
            kind="legislation",
            title="same",
            text="Texto integral do regulamento.\n\nArtigo 7.º",
            source_url="https://example.test/same",
        )
        self.assertEqual(folded["id"], record["id"])
        self.assertEqual(folded["id"], import_csv.document_id(" eur-lex ", folder, filename))

    def test_raw_payload_hash_matches_graph_contract(self) -> None:
        record = self._sample()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outcome = opensrc.commit_record(root, record)
            self.assertEqual(outcome["raw"], "written")
            raw_text = (root / record["rel_raw"]).read_text(encoding="utf-8")
            payload = build_connection_graph.full_text_payload(raw_text)
            self.assertEqual(build_connection_graph.sha256_text(payload), record["content_hash"])
            self.assertEqual(payload, record["text"])


class OpenSourceCommitTests(_RecordFactory, unittest.TestCase):
    def test_unchanged_rerun_does_not_rewrite_raw(self) -> None:
        record = self._sample()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = opensrc.commit_record(root, record)
            raw_path = root / record["rel_raw"]
            written = raw_path.read_bytes()
            second = opensrc.commit_record(root, record)
            self.assertEqual(first["raw"], "written")
            self.assertEqual(second["raw"], "unchanged")
            self.assertEqual(second["wiki"], "unchanged")
            self.assertEqual(raw_path.read_bytes(), written)

    def test_changed_content_is_reported_and_not_overwritten(self) -> None:
        original = self._sample()
        replacement = self._sample("Segunda versão, texto diferente.\n\nArtigo 5.º")
        self.assertEqual(original["id"], replacement["id"])
        self.assertNotEqual(original["content_hash"], replacement["content_hash"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opensrc.commit_record(root, original)
            outcome = opensrc.commit_record(root, replacement)
            self.assertEqual(outcome["raw"], "changed")
            self.assertEqual(outcome["wiki"], "skipped")
            raw_text = (root / original["rel_raw"]).read_text(encoding="utf-8")
            self.assertIn(original["content_hash"], raw_text)
            self.assertIn("Primeira versão", raw_text)
            self.assertNotIn("Segunda versão", raw_text)

    def test_catalog_row_shape(self) -> None:
        record = self._sample()
        row = opensrc.catalog_row(record)
        self.assertEqual(tuple(row.keys()), CATALOG_FIELDS)
        self.assertEqual(row["verification"], "unverified")
        self.assertEqual(row["kind"], "case_law")
        self.assertEqual(row["document_type"], "case-law")
        self.assertEqual(row["topic"], "Transporte aéreo — Regulamento 261/2004")
        self.assertEqual(row["topic_raw"], row["topic"])
        self.assertEqual(row["text_chars"], len(record["text"]))
        self.assertEqual(row["content_hash"], import_csv.content_hash(record["text"]))
        self.assertTrue(row["rel_raw"].startswith("raw/documents/opensrc/dgsi-stj/2024/law_"))
        self.assertTrue(row["rel_source"].startswith("wiki/sources/"))
        self.assertTrue(row["rel_source"].endswith(f"--{record['id']}.md"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opensrc.commit_record(root, record)
            count = opensrc.write_catalog(root, [record])
            catalog = (root / "data" / "open-sources-catalog.jsonl").read_text(encoding="utf-8")
            parsed = json.loads(catalog.strip())
            self.assertEqual(count, 1)
            self.assertEqual(parsed["id"], record["id"])
            self.assertEqual(parsed["verification"], "unverified")
            for field in CATALOG_FIELDS:
                self.assertIn(field, parsed)


class RobotsTests(unittest.TestCase):
    def test_missing_robots_allows_and_disallow_blocks(self) -> None:
        url = "https://www.dgsi.pt/jstj.nsf/example?OpenDocument"
        self.assertTrue(opensrc.robots_allowed(404, "", url))
        body = "User-agent: *\nDisallow: /jstj.nsf/\n"
        self.assertFalse(opensrc.robots_allowed(200, body, url))
        self.assertTrue(opensrc.robots_allowed(200, "User-agent: *\nAllow: /\n", url))
        self.assertFalse(opensrc.robots_allowed(503, "", url))


if __name__ == "__main__":
    unittest.main()
