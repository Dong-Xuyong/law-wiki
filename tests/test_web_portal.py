import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_web_catalog  # noqa: E402
import import_pdfs  # noqa: E402


class WebCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_jsonl(self, relative: str, rows: list[dict]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_web_catalog_merges_csv_and_pdf_records(self) -> None:
        base = {
            "id": "law_base", "title": "Base", "filename": "Base.pdf",
            "folder": "CICAP/Decisões", "year": "2023", "website": "CICAP",
            "topic": "Voos", "topic_raw": "Voos", "rel_raw": "raw/base.md",
            "rel_source": "wiki/base.md",
        }
        pdf = {
            "id": "law_pdf", "title": "PDF", "filename": "PDF.pdf",
            "folder": "PDFs/Fornecidos/2026", "year": "2026", "website": "Fornecidos",
            "topic": "PDF importado", "topic_raw": "PDF importado",
            "rel_raw": "raw/pdf.md", "rel_source": "wiki/pdf.md",
            "pdf_path": "raw/pdfs/Fornecidos/2026/PDF.pdf",
        }
        (self.root / pdf["pdf_path"]).parent.mkdir(parents=True)
        (self.root / pdf["pdf_path"]).write_bytes(b"%PDF")
        self.write_jsonl("data/catalog.jsonl", [base])
        self.write_jsonl("data/pdf-catalog.jsonl", [pdf])
        generated = self.root / "generated"
        public = self.root / "public" / "data"

        stats = build_web_catalog.build(self.root, generated, public)

        payload = json.loads((generated / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(stats["documents"], 2)
        self.assertEqual({row["id"] for row in payload["documents"]}, {"law_base", "law_pdf"})
        self.assertTrue((self.root / "public" / "pdfs" / "Fornecidos" / "2026" / "PDF.pdf").is_file())

    def test_folder_tree_is_nested_and_counted(self) -> None:
        tree = build_web_catalog.build_folder_tree([
            {"folder": "A/B", "title": "One"},
            {"folder": "A/C", "title": "Two"},
        ])
        self.assertEqual(tree[0]["name"], "A")
        self.assertEqual(tree[0]["count"], 2)
        self.assertEqual([node["name"] for node in tree[0]["children"]], ["B", "C"])


class PdfImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pdf = self.root / "raw" / "pdfs" / "Fornecidos" / "2026" / "Contrato.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b"%PDF-test")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_import_uses_folder_metadata_and_is_idempotent(self) -> None:
        extract = lambda _: "Texto integral do contrato."
        first = import_pdfs.import_pdfs(self.root, extractor=extract)
        second = import_pdfs.import_pdfs(self.root, extractor=extract)
        rows = [
            json.loads(line)
            for line in (self.root / "data" / "pdf-catalog.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(first["pdfs"], 1)
        self.assertEqual(second["pdfs"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["website"], "Fornecidos")
        self.assertEqual(rows[0]["year"], "2026")
        self.assertTrue((self.root / rows[0]["rel_raw"]).is_file())
        self.assertTrue((self.root / rows[0]["rel_source"]).is_file())

    def test_changed_extraction_is_protected(self) -> None:
        import_pdfs.import_pdfs(self.root, extractor=lambda _: "Primeira versão")
        result = import_pdfs.import_pdfs(self.root, extractor=lambda _: "Versão diferente")
        self.assertEqual(len(result["protected"]), 1)


if __name__ == "__main__":
    unittest.main()
