"""Offline tests for the FTS indexer and retriever."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.engine.retrieve import Retriever
from app.engine.retrieve.query import build_match_query, phrase_bonus
from app.engine.retrieve import s3_index
from app.ingest.index_fts import (
    body_start_line,
    build_index,
    passage_spans,
)

REPO = Path(__file__).resolve().parents[2]

DOC_A_LINES = [
    "---",
    'id: "doc_a"',
    'title: "Atraso"',
    "marker: frontmatteronlyaaa",
    "---",
    "",
    "# Atraso de voo",
    "",
    "## Full text",
    "",
    "O passageiro reclama indemnização por atraso de voo.",
    "O Regulamento 261/2004 aplica-se ao transporte aéreo.",
    "O artigo 7 estabelece os montantes da indemnização.",
]

DOC_C = (
    "---\n"
    'id: "doc_c"\n'
    "---\n"
    "\n"
    "# Acórdão\n"
    "\n"
    "## Full text\n"
    "\n"
    "O cancelamento do voo foi discutido neste acórdão.\n"
    "Não há diploma europeu neste texto.\n"
    "Referência solta 261 e depois 2004 sem barra."
)


def _expected_lines(raw: bytes) -> list[str]:
    text = raw.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _write_corpus(root: Path) -> dict[str, Path]:
    raw = root / "raw" / "documents"
    data = root / "data"
    raw.mkdir(parents=True)
    data.mkdir(parents=True)

    doc_a = "\n".join(DOC_A_LINES) + "\n"
    path_a = raw / "a.md"
    path_a.write_bytes(doc_a.replace("\n", "\r\n").encode("utf-8"))

    body = [f"enchimento {name}" for name in (
        "alfa", "beta", "gama", "delta", "epsilon", "zeta", "eta", "iota",
        "kappa", "lambda", "mi", "ni", "xi", "omicron", "pi", "rho",
        "sigma", "tau", "upsilon", "phi",
    )]
    body[0] = "inicio starttokenalfa regulamento comunitário"
    body[10] = "meio midtokenalfa circunstâncias extraordinárias do transporte"
    body[19] = "fim endtokenalfa com reembolso nos termos do artigo 8"
    doc_b_lines = ["---", 'id: "doc_b"', "---", *body]
    path_b = raw / "b.md"
    path_b.write_text("\n".join(doc_b_lines) + "\n", encoding="utf-8")

    path_c = raw / "c.md"
    path_c.write_bytes(DOC_C.encode("utf-8"))

    primary = [
        {
            "id": "doc_a",
            "title": "Decisão sobre atraso de voo",
            "rel_raw": "raw/documents/a.md",
            "rel_source": "wiki/sources/doc_a.md",
            "website": "CAA",
            "year": "2024",
        },
        {
            "id": "doc_missing",
            "title": "Ausente",
            "rel_raw": "raw/documents/missing.md",
            "rel_source": "wiki/sources/missing.md",
            "website": "CAA",
            "year": "2020",
        },
        "{not json",
        {
            "id": "doc_escape",
            "title": "Fora",
            "rel_raw": "../outside.md",
            "website": "CAA",
            "year": "2020",
        },
    ]
    secondary = [
        {
            "id": "doc_b",
            "title": "Regulamento 261/2004",
            "rel_raw": "raw/documents/b.md",
            "rel_source": "wiki/sources/doc_b.md",
            "website": "EUR-Lex",
            "year": "2004",
            "kind": "legislation",
            "source_url": "https://example.invalid/261",
        },
        {
            "id": "doc_a",
            "title": "Não deve substituir",
            "rel_raw": "raw/documents/a.md",
            "rel_source": "wiki/sources/doc_a.md",
            "website": "EUR-Lex",
            "year": "2004",
            "kind": "legislation",
            "source_url": "https://example.invalid/dup",
        },
        {
            "id": "doc_c",
            "title": "Acórdão de cancelamento",
            "rel_raw": "raw/documents/c.md",
            "rel_source": None,
            "website": "CJUE",
            "year": 2019,
            "kind": "case_law",
            "source_url": "https://example.invalid/case",
        },
    ]
    (data / "catalog.jsonl").write_text(_jsonl(primary), encoding="utf-8")
    (data / "open-sources-catalog.jsonl").write_text(
        _jsonl(secondary), encoding="utf-8"
    )
    return {"a": path_a, "b": path_b, "c": path_c}


def _jsonl(rows: list) -> str:
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines) + "\n"


class QueryBuilderTests(unittest.TestCase):
    def test_strips_fts_operators_and_punctuation(self) -> None:
        prepared = build_match_query('foo" OR * NEAR(bar)')
        self.assertEqual(prepared.match, '"foo" OR "bar"')
        self.assertNotIn("*", prepared.match or "")
        self.assertNotIn("NEAR", prepared.match or "")
        self.assertEqual(prepared.slash_phrases, ())
        self.assertEqual(prepared.artigo_numbers, ())

    def test_empty_and_operators_only(self) -> None:
        for query in ("", "   ", "***", "NEAR OR AND NOT", '"', ")("):
            self.assertIsNone(build_match_query(query).match)

    def test_slash_and_artigo_phrases(self) -> None:
        prepared = build_match_query(
            "indemnização Regulamento 261/2004 artigo 7"
        )
        self.assertEqual(
            prepared.match,
            '"indemnização" OR "Regulamento" OR "261" OR "2004" OR "artigo" '
            'OR "7" OR "261 2004" OR "artigo 7"',
        )
        self.assertEqual(prepared.slash_phrases, ("261/2004",))
        self.assertEqual(prepared.artigo_numbers, ("7",))

    def test_phrase_bonus_is_literal(self) -> None:
        prepared = build_match_query("261/2004 artigo 8")
        self.assertGreater(
            phrase_bonus("Regulamento 261/2004 e o artigo 8", prepared), 0
        )
        self.assertGreater(phrase_bonus("Artigo   8.º", prepared), 0)
        self.assertEqual(phrase_bonus("261 e 2004 e artigo 9", prepared), 0)


class WindowTests(unittest.TestCase):
    def test_frontmatter_and_spans(self) -> None:
        lines = ["---", "a: 1", "---", "", "body"]
        self.assertEqual(body_start_line(lines), 4)
        self.assertEqual(body_start_line(["no", "front"]), 1)
        self.assertEqual(body_start_line(["---", "a: 1"]), 1)
        self.assertEqual(passage_spans(6, 25), [(6, 17), (14, 25)])
        first, second = passage_spans(6, 25)
        self.assertEqual(first[1] - second[0] + 1, 4)
        self.assertEqual(passage_spans(1, 12), [(1, 12)])
        self.assertEqual(passage_spans(1, 13), [(1, 12), (9, 13)])
        self.assertEqual(passage_spans(1, 0), [])
        self.assertEqual(passage_spans(5, 4), [])


class IndexAndRetrieveTests(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory
    root: Path
    paths: dict[str, Path]
    out: Path
    stats: dict
    retriever: Retriever

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.paths = _write_corpus(cls.root)
        cls.out = cls.root / "index dir" / "idx.sqlite3"
        cls.stats = build_index(cls.root, cls.out)
        cls.retriever = Retriever(cls.out)
        cls.addClassCleanup(cls.retriever.close)

    def test_index_counts_and_skips(self) -> None:
        self.assertEqual(self.stats["docs"], 3)
        self.assertGreater(self.stats["passages"], 0)
        self.assertGreater(self.stats["lines"], self.stats["docs"])
        self.assertGreater(self.stats["size_bytes"], 0)
        self.assertGreaterEqual(self.stats["seconds"], 0)
        reasons = " ".join(row["reason"] for row in self.stats["skipped_rows"])
        self.assertIn("missing file", reasons)
        self.assertIn("invalid json", reasons)
        self.assertIn("duplicate id", reasons)
        self.assertIn("path outside root", reasons)
        self.assertEqual(self.stats["kinds"]["arbitral"], 1)
        self.assertEqual(self.stats["kinds"]["legislation"], 1)
        self.assertEqual(self.stats["kinds"]["case_law"], 1)
        self.assertFalse(self.out.with_name(self.out.name + ".tmp").exists())

    def test_schema(self) -> None:
        conn = sqlite3.connect(self.out)
        try:
            docs_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='docs'"
            ).fetchone()[0]
            lines_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='lines'"
            ).fetchone()[0]
            passages_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='passages'"
            ).fetchone()[0]
            doc_cols = [row[1] for row in conn.execute("PRAGMA table_info(docs)")]
            line_cols = [row[1] for row in conn.execute("PRAGMA table_info(lines)")]
        finally:
            conn.close()
        self.assertIn("WITHOUT ROWID", lines_sql.upper())
        self.assertIn("unicode61", passages_sql)
        self.assertIn("remove_diacritics 2", passages_sql)
        self.assertIn("UNINDEXED", passages_sql.upper())
        self.assertEqual(
            doc_cols,
            [
                "document_id",
                "path",
                "title",
                "website",
                "year",
                "kind",
                "rel_source",
                "line_count",
            ],
        )
        self.assertEqual(line_cols, ["document_id", "line_no", "text"])
        self.assertIn("document_id", docs_sql)

    def test_lines_are_exact_and_one_based(self) -> None:
        for doc_id, key in (("doc_a", "a"), ("doc_b", "b"), ("doc_c", "c")):
            expected = _expected_lines(self.paths[key].read_bytes())
            self.assertEqual(
                self.retriever.lines(doc_id, 1, len(expected)),
                "\n".join(expected),
            )
            self.assertNotIn("\r", self.retriever.lines(doc_id, 1, len(expected)))
        self.assertEqual(self.retriever.lines("doc_a", 1, 1), "---")
        self.assertEqual(self.retriever.lines("doc_a", 2, 2), 'id: "doc_a"')
        self.assertEqual(self.retriever.lines("doc_a", 5, 6), "---\n")
        self.assertEqual(self.retriever.lines("doc_a", 4, 2), "")

    def test_passages_skip_frontmatter_and_overlap(self) -> None:
        self.assertEqual(self.retriever.search("frontmatteronlyaaa"), [])
        start = self.retriever.search("starttokenalfa")
        end = self.retriever.search("endtokenalfa")
        mid = self.retriever.search("midtokenalfa")
        self.assertEqual(len(start), 1)
        self.assertEqual(len(end), 1)
        self.assertEqual(len(mid), 2)
        self.assertGreater(start[0]["line_start"], 3)
        self.assertNotIn('id: "doc_b"', start[0]["text"])
        self.assertEqual(end[0]["line_end"], len(_expected_lines(self.paths["b"].read_bytes())))
        starts = sorted(hit["line_start"] for hit in mid)
        self.assertEqual(starts[1] - starts[0], 8)
        for hit in (*start, *end, *mid):
            self.assertEqual(hit["line_end"] - hit["line_start"] + 1, 12)
            self.assertEqual(
                hit["text"],
                self.retriever.lines(
                    hit["document_id"], hit["line_start"], hit["line_end"]
                ),
            )

    def test_search_ranking_filters_and_diacritics(self) -> None:
        indemnity = self.retriever.search("indemnização atraso voo")
        self.assertEqual(indemnity[0]["document_id"], "doc_a")
        self.assertIn("indemnização", indemnity[0]["text"])
        folded = self.retriever.search("indemnizacao")
        self.assertTrue(folded)
        self.assertEqual(folded[0]["document_id"], "doc_a")
        self.assertIn("indemnização", folded[0]["text"])

        circumstances = self.retriever.search("circunstâncias extraordinárias")
        self.assertTrue(circumstances)
        self.assertTrue(all(hit["document_id"] == "doc_b" for hit in circumstances))
        folded_circumstances = self.retriever.search("circunstancias extraordinarias")
        self.assertTrue(
            any(hit["document_id"] == "doc_b" for hit in folded_circumstances)
        )

        article = self.retriever.search("cancelamento reembolso artigo 8")
        self.assertEqual(article[0]["document_id"], "doc_b")
        citation = self.retriever.search("261/2004")
        self.assertEqual(citation[0]["document_id"], "doc_a")
        self.assertIn("261/2004", citation[0]["text"])

        scores = [hit["score"] for hit in indemnity]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(
            set(indemnity[0]),
            {
                "document_id",
                "path",
                "title",
                "line_start",
                "line_end",
                "text",
                "score",
            },
        )
        self.assertIsInstance(indemnity[0]["score"], float)
        self.assertEqual(len(self.retriever.search("voo", k=1)), 1)
        self.assertEqual(self.retriever.search("voo", k=0), [])

        legislation = self.retriever.search(
            "regulamento", filters={"kind": "legislation"}
        )
        self.assertTrue(legislation)
        self.assertTrue(all(hit["document_id"] == "doc_b" for hit in legislation))
        arbitral = self.retriever.search(
            "regulamento", filters={"kind": "arbitral", "website": "CAA"}
        )
        self.assertTrue(arbitral)
        self.assertTrue(all(hit["document_id"] == "doc_a" for hit in arbitral))
        by_year = self.retriever.search("cancelamento", filters={"year": 2019})
        self.assertTrue(by_year)
        self.assertTrue(all(hit["document_id"] == "doc_c" for hit in by_year))
        self.assertEqual(
            self.retriever.search("voo", filters={"website": "CAA", "year": 1999}),
            [],
        )
        self.assertEqual(
            self.retriever.search("voo", filters={"kind": "case_law"})[0][
                "document_id"
            ],
            "doc_c",
        )
        self.assertTrue(
            self.retriever.search("starttokenalfa", filters={"not_a_filter": "x"})
        )
        self.assertEqual(
            self.retriever.search("starttokenalfa", filters=None)[0]["document_id"],
            self.retriever.search("starttokenalfa", filters={})[0]["document_id"],
        )

    def test_fts_injection_does_not_raise(self) -> None:
        nasty = [
            '"',
            "*",
            "NEAR",
            "foo OR bar",
            "(foo)",
            "a NEAR b",
            "NOT (foo)",
            '"unclosed',
            "o'brien",
            "***",
            "artigo: 7",
            "261/2004 AND cancelamento",
            ")(",
            "'",
            "foo*",
            "NEAR(foo, 2)",
        ]
        for query in nasty:
            hits = self.retriever.search(query, k=3)
            self.assertIsInstance(hits, list)
        boosted = self.retriever.search("261/2004 AND cancelamento")
        self.assertEqual(boosted[0]["document_id"], "doc_a")

    def test_verify_quote(self) -> None:
        lines = _expected_lines(self.paths["a"].read_bytes())
        start = next(
            index for index, line in enumerate(lines, 1) if "indemnização" in line
        )
        self.assertTrue(
            self.retriever.verify_quote(
                "doc_a", start, start, "reclama indemnização por"
            )
        )
        self.assertTrue(
            self.retriever.verify_quote(
                "doc_a", start, start, "reclama   indemnização\tpor"
            )
        )
        self.assertTrue(
            self.retriever.verify_quote(
                "doc_a", start, start + 1, "voo.\nO Regulamento"
            )
        )
        self.assertTrue(
            self.retriever.verify_quote(
                "doc_a", start, start + 1, "voo. O Regulamento"
            )
        )
        self.assertFalse(
            self.retriever.verify_quote("doc_a", start, start, "voo. O Regulamento")
        )
        self.assertFalse(
            self.retriever.verify_quote(
                "doc_a", start, start, "reclama indemnizacao por"
            )
        )
        self.assertFalse(
            self.retriever.verify_quote(
                "doc_a", start, start, "reclama compensação por"
            )
        )
        self.assertFalse(
            self.retriever.verify_quote(
                "doc_a", start, start, "Reclama indemnização por"
            )
        )

    def test_catalog_shape(self) -> None:
        catalog = self.retriever.catalog()
        self.assertEqual(set(catalog), {"doc_a", "doc_b", "doc_c"})
        for info in catalog.values():
            self.assertEqual(set(info), {"path", "title", "rel_source"})
        self.assertEqual(catalog["doc_a"]["path"], "raw/documents/a.md")
        self.assertEqual(catalog["doc_a"]["title"], "Decisão sobre atraso de voo")
        self.assertEqual(catalog["doc_a"]["rel_source"], "wiki/sources/doc_a.md")
        self.assertIsNone(catalog["doc_c"]["rel_source"])
        self.assertEqual(catalog["doc_c"]["title"], "Acórdão de cancelamento")
        self.assertNotIn("doc_missing", catalog)

    def test_connection_is_read_only(self) -> None:
        with self.assertRaises(sqlite3.OperationalError):
            self.retriever._conn.execute(
                "INSERT INTO docs(document_id, path, title, kind, line_count) "
                "VALUES ('x', 'p', 't', 'arbitral', 0)"
            )

    def test_search_is_safe_across_threads(self) -> None:
        errors: list[BaseException] = []

        def run() -> None:
            try:
                self.retriever.search("voo", k=3)
                self.retriever.lines("doc_a", 1, 3)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

    def test_second_build_replaces_atomically(self) -> None:
        out = self.root / "twice.sqlite3"
        build_index(self.root, out)
        build_index(self.root, out)
        self.assertTrue(out.is_file())
        self.assertFalse(out.with_name(out.name + ".tmp").exists())
        with Retriever(out) as retriever:
            self.assertIn("doc_b", retriever.catalog())

    def test_cli_prints_summary(self) -> None:
        out = self.root / "cli.sqlite3"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.ingest.index_fts",
                "--root",
                str(self.root),
                "--out",
                str(out),
            ],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("docs=3", result.stdout)
        self.assertIn(f"skipped={self.stats['skipped']}", result.stdout)
        self.assertIn("size_mb=", result.stdout)
        self.assertIn("duration_s=", result.stdout)
        self.assertIn("SKIP missing file", result.stdout)
        self.assertTrue(out.is_file())


class EnsureLocalIndexTests(unittest.TestCase):
    def test_local_default_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LW_CORPUS_BUCKET", None)
            os.environ.pop("LW_INDEX_PATH", None)
            self.assertEqual(s3_index.ensure_local_index(), Path("build/index/fts.sqlite3"))
        with patch.dict(
            os.environ,
            {"LW_INDEX_PATH": r"C:\custom\fts.sqlite3"},
            clear=False,
        ):
            os.environ.pop("LW_CORPUS_BUCKET", None)
            self.assertEqual(
                s3_index.ensure_local_index(), Path(r"C:\custom\fts.sqlite3")
            )

    def test_bucket_downloads_once_and_ignores_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fts.sqlite3"
            calls: list[tuple[str, str, str]] = []

            class FakeClient:
                def download_file(self, bucket: str, key: str, filename: str) -> None:
                    calls.append((bucket, key, filename))
                    Path(filename).write_text("db", encoding="utf-8")

            fake_boto3 = type(
                "Boto3", (), {"client": staticmethod(lambda *a, **k: FakeClient())}
            )()
            old_cache = s3_index.CACHE_PATH
            s3_index.CACHE_PATH = dest
            try:
                with patch.dict(
                    os.environ,
                    {
                        "LW_CORPUS_BUCKET": "law-bucket",
                        "LW_INDEX_PATH": r"C:\ignored\fts.sqlite3",
                        "LW_REGION": "eu-west-1",
                    },
                    clear=False,
                ):
                    os.environ.pop("LW_INDEX_S3_KEY", None)
                    with patch.dict(sys.modules, {"boto3": fake_boto3}):
                        path = s3_index.ensure_local_index()
                        again = s3_index.ensure_local_index()
                self.assertEqual(path, dest)
                self.assertEqual(again, dest)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], "law-bucket")
                self.assertEqual(calls[0][1], "index/fts.sqlite3")
                self.assertTrue(str(calls[0][2]).endswith(".partial"))
                self.assertEqual(dest.read_text(encoding="utf-8"), "db")
            finally:
                s3_index.CACHE_PATH = old_cache

    def test_existing_cache_does_not_import_boto3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fts.sqlite3"
            dest.write_text("ready", encoding="utf-8")
            old_cache = s3_index.CACHE_PATH
            s3_index.CACHE_PATH = dest

            class Boom:
                def __getattr__(self, name: str) -> None:
                    raise AssertionError(name)

            try:
                with patch.dict(os.environ, {"LW_CORPUS_BUCKET": "law-bucket"}):
                    with patch.dict(sys.modules, {"boto3": Boom()}):
                        self.assertEqual(s3_index.ensure_local_index(), dest)
            finally:
                s3_index.CACHE_PATH = old_cache

    def test_failed_download_removes_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fts.sqlite3"

            class FakeClient:
                def download_file(self, bucket: str, key: str, filename: str) -> None:
                    Path(filename).write_text("partial", encoding="utf-8")
                    raise RuntimeError("network")

            fake_boto3 = type(
                "Boto3", (), {"client": staticmethod(lambda *a, **k: FakeClient())}
            )()
            old_cache = s3_index.CACHE_PATH
            s3_index.CACHE_PATH = dest
            try:
                with patch.dict(os.environ, {"LW_CORPUS_BUCKET": "law-bucket"}):
                    os.environ.pop("LW_INDEX_S3_KEY", None)
                    with patch.dict(sys.modules, {"boto3": fake_boto3}):
                        with self.assertRaises(RuntimeError):
                            s3_index.ensure_local_index()
            finally:
                s3_index.CACHE_PATH = old_cache
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name(dest.name + ".partial").exists())


if __name__ == "__main__":
    unittest.main()
