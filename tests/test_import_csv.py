import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_csv  # noqa: E402


SAMPLE_CSV = """folder,filename,text,is_empty,year,website,Topic,tokens,summary,tokens_sm
"Folder A","Doc One.pdf","Line1
Line2 ""quoted""
Line3",True,2023,CACCL,garantias/defeitos,10,"Summary A",4
"Folder B","Doc One.pdf","Different text",False,2022,CICAP,Energia,5,Summary B,2
"Folder C","Dup.pdf","SAME BODY",False,2021,Triave,Legislacao,3,Sum A,1
"Folder D","Dup2.pdf","SAME BODY",False,2021,Triave,Legislacao,3,Sum B,1
"""


class ImportCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "topic-map.json").write_text(
            json.dumps(
                {
                    "topics": {
                        "garantias/defeitos": {
                            "kind": "subject",
                            "sector": "consumer-goods",
                            "categories": ["guarantees-and-defects"],
                        },
                        "Legislacao": {
                            "kind": "document-genre",
                            "sector": None,
                            "categories": ["legislation"],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        self.csv_path = self.root / "sample.csv"
        self.csv_path.write_text(SAMPLE_CSV, encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_page(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def test_multiline_and_quotes_parse(self) -> None:
        rows = import_csv.read_rows(self.csv_path)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["text"], "Line1\nLine2 \"quoted\"\nLine3")
        self.assertEqual(rows[0]["is_empty"], "True")

    def test_same_filename_different_folders_get_distinct_ids(self) -> None:
        rows = import_csv.read_rows(self.csv_path)
        a = import_csv.enrich_record(rows[0])
        b = import_csv.enrich_record(rows[1])
        self.assertEqual(a["filename"], b["filename"])
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(a["source_slug"], b["source_slug"])

    def test_duplicate_text_stays_two_documents(self) -> None:
        report = import_csv.import_corpus(self.csv_path, self.root)
        self.assertEqual(report["stats"]["rows"], 4)
        self.assertEqual(report["stats"]["duplicate_groups"], 1)
        self.assertEqual(report["stats"]["duplicate_rows"], 2)
        raw_files = list((self.root / "raw" / "documents").rglob("*.md"))
        source_files = list((self.root / "wiki" / "sources").glob("*.md"))
        self.assertEqual(len(raw_files), 4)
        self.assertEqual(len(source_files), 4)

    def test_is_empty_true_is_not_filtered(self) -> None:
        report = import_csv.import_corpus(self.csv_path, self.root)
        catalog = [
            json.loads(line)
            for line in (self.root / "data" / "catalog.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        empty_flags = {row["id"]: row["is_empty"] for row in catalog}
        self.assertIn("True", empty_flags.values())
        self.assertEqual(report["stats"]["rows"], 4)

    def test_deterministic_ids(self) -> None:
        first = import_csv.document_id("CACCL", "Folder A", "Doc One.pdf")
        second = import_csv.document_id("caccl", "Folder A", "Doc One.pdf")
        third = import_csv.document_id("CICAP", "Folder A", "Doc One.pdf")
        self.assertTrue(first.startswith("law_"))
        self.assertEqual(len(first), 20)
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_idempotent_rerun_skips_unchanged_raw(self) -> None:
        import_csv.import_corpus(self.csv_path, self.root)
        tracked = [
            self.root / "wiki" / "index.md",
            *sorted((self.root / "wiki" / "sources").glob("*.md")),
            *sorted((self.root / "wiki" / "indexes").rglob("*.md")),
        ]
        before = {path: path.read_bytes() for path in tracked}
        again = import_csv.import_corpus(self.csv_path, self.root)
        self.assertEqual(again["stats"]["raw_written"], 0)
        self.assertEqual(again["stats"]["raw_unchanged"], 4)
        self.assertEqual(again["stats"]["raw_changed"], 0)
        self.assertEqual(again["stats"]["sources_written"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in tracked})

    def test_idempotent_generated_outputs_across_run_dates(self) -> None:
        original_today = import_csv.today_iso
        try:
            import_csv.today_iso = lambda: "2026-01-01"
            import_csv.import_corpus(self.csv_path, self.root)
            source = next((self.root / "wiki" / "sources").glob("*.md"))
            before = source.read_bytes()
            import_csv.today_iso = lambda: "2026-01-02"
            report = import_csv.import_corpus(self.csv_path, self.root)
            self.assertEqual(report["stats"]["sources_written"], 0)
            self.assertEqual(before, source.read_bytes())
        finally:
            import_csv.today_iso = original_today

    def test_reports_raw_content_change_without_overwrite(self) -> None:
        import_csv.import_corpus(self.csv_path, self.root)
        rows = import_csv.read_rows(self.csv_path)
        record = import_csv.enrich_record(rows[0])
        raw_path = self.root / record["rel_raw"]
        raw_path.write_text(
            raw_path.read_text(encoding="utf-8").replace(
                f"content_hash: {json.dumps(record['content_hash'])}",
                'content_hash: "deadbeef"',
            ),
            encoding="utf-8",
        )
        before = raw_path.read_text(encoding="utf-8")
        report = import_csv.import_corpus(self.csv_path, self.root)
        after = raw_path.read_text(encoding="utf-8")
        self.assertEqual(report["stats"]["raw_changed"], 1)
        self.assertEqual(before, after)
        self.assertTrue(any(record["id"] in item for item in report["content_change_reports"]))

    def test_skips_enriched_source_pages(self) -> None:
        import_csv.import_corpus(self.csv_path, self.root)
        rows = import_csv.read_rows(self.csv_path)
        record = import_csv.enrich_record(rows[0])
        source_path = self.root / record["rel_source"]
        original = source_path.read_text(encoding="utf-8")
        source_path.write_text(
            original.replace("enriched: false", "enriched: true").replace(
                "## Summary", "## Summary\n\nLLM ENRICHED KEEP ME\n\n## Summary"
            ),
            encoding="utf-8",
        )
        marker = "LLM ENRICHED KEEP ME"
        import_csv.import_corpus(self.csv_path, self.root)
        self.assertIn(marker, source_path.read_text(encoding="utf-8"))
        self.assertEqual(
            import_csv.import_corpus(self.csv_path, self.root)["stats"]["protected_conflicts"],
            1,
        )

    def test_topic_map_exact_label_and_source_schema(self) -> None:
        import_csv.import_corpus(self.csv_path, self.root)
        rows = import_csv.read_rows(self.csv_path)
        mapped = import_csv.enrich_record(rows[0], import_csv.load_topic_map(self.root))
        self.assertEqual(mapped["topic_raw"], "garantias/defeitos")
        self.assertEqual(mapped["sector"], "consumer-goods")
        self.assertEqual(mapped["categories"], ["guarantees-and-defects"])
        source = (self.root / mapped["rel_source"]).read_text(encoding="utf-8")
        for field in (
            "document_type:", "process_number:", "case:", "forum:", "decision_date:",
            "sectors:", "doctrines:", "cited_instruments:", "outcome_status:",
            "duplicate_of:", "family:", "enrichment_state:", "extractor_version:",
            "summary_hash:", "generated_fingerprint:",
        ):
            self.assertIn(field, source)
        self.assertIn('verification: "unverified"', source)

    def test_modified_seed_pages_are_protected(self) -> None:
        import_csv.import_corpus(self.csv_path, self.root)
        entity = self.root / "wiki" / "entities" / "caccl.md"
        entity.write_text(entity.read_text(encoding="utf-8") + "\nHUMAN NOTE\n", encoding="utf-8")
        report = import_csv.import_corpus(self.csv_path, self.root)
        self.assertIn("HUMAN NOTE", entity.read_text(encoding="utf-8"))
        self.assertTrue(any("entity:" in item for item in report["protected_conflict_reports"]))

    def test_exact_v1_pages_migrate_to_fingerprinted_v2(self) -> None:
        imported = "2025-12-31"
        records = [
            import_csv.enrich_record(row, import_csv.load_topic_map(self.root))
            for row in import_csv.read_rows(self.csv_path)
        ]
        websites = {}
        topics = {}
        for record in records:
            websites.setdefault(record["website"], []).append(record)
            topics.setdefault(record["topic_raw"], []).append(record)
        first = records[0]
        self.write_page(
            first["rel_source"], import_csv.legacy_v1_source_markdown(first, imported)
        )
        self.write_page(
            "wiki/entities/caccl.md",
            import_csv.legacy_v1_entity_markdown("CACCL", "caccl", websites["CACCL"], imported),
        )
        self.write_page(
            "wiki/concepts/garantias-defeitos.md",
            import_csv.legacy_v1_concept_markdown(
                "garantias/defeitos", "garantias-defeitos",
                topics["garantias/defeitos"], imported,
            ),
        )
        shard = self.write_page(
            "wiki/indexes/by-topic/garantias-defeitos.md",
            import_csv.legacy_v1_index_shard(
                "Topic", "garantias/defeitos", topics["garantias/defeitos"]
            ),
        )
        master = self.write_page(
            "wiki/index.md",
            import_csv.legacy_v1_master_index(records, websites, topics),
        )
        csv_meta = {
            "path": str(self.csv_path),
            "size": self.csv_path.stat().st_size,
            "sha256": import_csv.file_sha256(self.csv_path),
        }
        overview = self.write_page(
            "wiki/overview.md",
            import_csv.legacy_v1_overview(
                records, websites, topics, 1, 4, imported, csv_meta
            ),
        )
        report = import_csv.import_corpus(self.csv_path, self.root)
        migrated = [
            self.root / first["rel_source"],
            self.root / "wiki/entities/caccl.md",
            self.root / "wiki/concepts/garantias-defeitos.md",
            shard, master, overview,
        ]
        self.assertGreaterEqual(report["stats"]["legacy_v1_migrated"], len(migrated))
        for path in migrated:
            content = path.read_text(encoding="utf-8")
            self.assertIn("generated_fingerprint:", content)
            self.assertTrue(import_csv.fingerprint_valid(content))
        self.assertIn("topic_raw:", (self.root / first["rel_source"]).read_text(encoding="utf-8"))

    def test_one_character_v1_edits_remain_protected(self) -> None:
        imported = "2025-12-31"
        records = [
            import_csv.enrich_record(row, import_csv.load_topic_map(self.root))
            for row in import_csv.read_rows(self.csv_path)
        ]
        first = records[0]
        source = self.write_page(
            first["rel_source"],
            import_csv.legacy_v1_source_markdown(first, imported).replace(
                "Summary A", "Summary X", 1
            ),
        )
        topic_group = [record for record in records if record["topic_raw"] == first["topic_raw"]]
        shard = self.write_page(
            "wiki/indexes/by-topic/garantias-defeitos.md",
            import_csv.legacy_v1_index_shard(
                "Topic", first["topic_raw"], topic_group
            ).replace("Topic:", "Topix:", 1),
        )
        source_before, shard_before = source.read_bytes(), shard.read_bytes()
        report = import_csv.import_corpus(self.csv_path, self.root)
        self.assertEqual(source_before, source.read_bytes())
        self.assertEqual(shard_before, shard.read_bytes())
        conflicts = "\n".join(report["protected_conflict_reports"])
        self.assertIn("source:", conflicts)
        self.assertIn("dimension-page:", conflicts)

    def test_paginates_dimension_with_stable_hub_and_navigation(self) -> None:
        many = self.root / "many.csv"
        with many.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(import_csv.EXPECTED_COLUMNS)
            for number in range(201):
                writer.writerow([
                    "One Folder", f"Doc {number}.pdf", f"text {number}", "False",
                    "2024", "One Site", "Energia", "1", f"summary {number}", "1",
                ])
        legacy_records = [
            import_csv.enrich_record(row, import_csv.load_topic_map(self.root))
            for row in import_csv.read_rows(many)
        ]
        self.write_page(
            "wiki/indexes/by-topic/energia.md",
            import_csv.legacy_v1_index_shard("Topic", "Energia", legacy_records),
        )
        report = import_csv.import_corpus(many, self.root)
        hub = self.root / "wiki" / "indexes" / "by-topic" / "energia.md"
        page1 = self.root / "wiki" / "indexes" / "by-topic" / "energia--page-001.md"
        page2 = self.root / "wiki" / "indexes" / "by-topic" / "energia--page-002.md"
        self.assertTrue(hub.exists())
        self.assertIn("[[indexes/by-topic/energia--page-001|Page 1]]", hub.read_text(encoding="utf-8"))
        self.assertIn("Parent: [[indexes/by-topic/energia]]", page1.read_text(encoding="utf-8"))
        self.assertIn("Next: [[indexes/by-topic/energia--page-002]]", page1.read_text(encoding="utf-8"))
        self.assertIn("Previous: [[indexes/by-topic/energia--page-001]]", page2.read_text(encoding="utf-8"))
        self.assertGreaterEqual(report["stats"]["legacy_v1_migrated"], 1)

    def test_indexes_and_unverified_summaries(self) -> None:
        import_csv.import_corpus(self.csv_path, self.root)
        index = (self.root / "wiki" / "index.md").read_text(encoding="utf-8")
        overview = (self.root / "wiki" / "overview.md").read_text(encoding="utf-8")
        home = (self.root / "wiki" / "home.md").read_text(encoding="utf-8")
        source = next((self.root / "wiki" / "sources").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("[[indexes/by-topic/", index)
        self.assertIn("[[indexes/by-year/index|Years]]", index)
        self.assertIn("[[indexes/by-folder/index|Folders]]", index)
        self.assertIn("[[cases/index|Cases]]", home)
        self.assertTrue((self.root / "wiki" / "families" / "index.md").is_file())
        self.assertIn("does not state legal conclusions", overview)
        self.assertIn("**Unverified**", source)
        self.assertIn("verification: \"unverified\"", source)
        self.assertTrue(source.startswith("---"))
        self.assertGreaterEqual(source.count("---"), 2)


if __name__ == "__main__":
    unittest.main()
