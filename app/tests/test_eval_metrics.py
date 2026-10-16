"""Offline checks for eval metrics and the twenty case files."""

from __future__ import annotations

import json
import re
import unittest
from decimal import Decimal
from pathlib import Path

from app.eval.metrics import evaluate

ROOT = Path(__file__).resolve().parents[2]
FICTIONAL = ROOT / "app" / "eval" / "cases" / "fictional"
BACKTEST = ROOT / "app" / "eval" / "cases" / "backtest"
MONEY = re.compile(r"^\d+\.\d{2}$")
WORD = re.compile(r"\S+")
OUTCOMES = {"procedente", "parcialmente procedente", "improcedente"}


def _lines(relative: str) -> list[str]:
    text = (ROOT / relative).read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.splitlines()


def _overlaps(left: list[int], right: list[int]) -> bool:
    return not (left[1] < right[0] or right[1] < left[0])


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


class FakeRetriever:
    def __init__(self, documents: dict[str, str], reject_quotes: bool = False) -> None:
        self.documents = documents
        self.reject_quotes = reject_quotes

    def line_count(self, document_id: str) -> int:
        return len(self.documents[document_id].splitlines())

    def lines(self, document_id: str, line_start: int, line_end: int) -> str:
        rows = self.documents[document_id].splitlines()
        return "\n".join(rows[line_start - 1 : line_end])

    def verify_quote(self, document_id: str, line_start: int, line_end: int, quote: str) -> bool:
        if self.reject_quotes:
            return False
        text = " ".join(self.lines(document_id, line_start, line_end).split())
        return " ".join(quote.split()) in text


def _catalog() -> dict:
    return {
        "law_aaaaaaaaaaaaaaaa": {
            "path": "raw/documents/example/2024/law_aaaaaaaaaaaaaaaa.md",
            "title": "Exemplo",
            "rel_source": "wiki/sources/example--law_aaaaaaaaaaaaaaaa.md",
        }
    }


def _packet(**overrides) -> dict:
    law = (
        "O artigo dispõe que «os passageiros devem receber uma indemnização» "
        "quando o atraso de chegada atinge três horas."
    )
    packet = {
        "sources": [
            {
                "id": "ex",
                "title": "Exemplo",
                "path": "raw/documents/example/2024/law_aaaaaaaaaaaaaaaa.md",
                "document_id": "law_aaaaaaaaaaaaaaaa",
                "pinpoints": ["linhas 1–2"],
            }
        ],
        "evidence_matrix": [
            {
                "id": "f1",
                "proposition": "O voo chegou com três horas de atraso.",
                "status": "proved",
                "basis": "admission",
            },
            {
                "id": "n1",
                "proposition": "Houve trovoada.",
                "status": "not_proved",
                "basis": "unilateral_assertion",
            },
        ],
        "sections": {
            "sumario": [{"text": f"{index}. Ponto."} for index in range(1, 5)],
            "relatorio": [{"text": "Relatório."}],
            "objeto_litigio": [{"text": "Objeto."}],
            "saneador": [{"text": "Saneador."}],
            "factos_provados": [{"text": "a) Atraso.", "evidence_ids": ["f1"]}],
            "factos_nao_provados": [{"text": "aa) Trovoada.", "evidence_ids": ["n1"]}],
            "motivacao": [{"text": "Motivação."}],
            "fundamentacao_direito": [{"text": law, "source_ids": ["ex"]}],
            "decisao": [{"text": "Julga-se procedente. artigo 7.º"}],
        },
        "amounts": [
            {"item": "Indemnização", "claimed": "250.00", "awarded": "250.00", "reason": "Banda."}
        ],
        "decision_total": "250.00",
    }
    packet.update(overrides)
    return packet


class MetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = _catalog()
        self.retriever = FakeRetriever(
            {
                "law_aaaaaaaaaaaaaaaa": "\n".join(
                    [
                        "Linha inicial do documento.",
                        "os passageiros devem receber uma indemnização no artigo citado.",
                    ]
                )
            }
        )
        self.expected = {
            "decision_total": "250.00",
            "must_mention": ["artigo 7.º"],
        }

    def test_passing_packet_scores_one(self) -> None:
        report = evaluate(_packet(), self.catalog, self.retriever, self.expected)
        for name in (
            "citation_existence",
            "evidence_linkage",
            "amounts",
            "section_completeness",
            "must_mention",
        ):
            self.assertEqual(report[name]["ratio"], 1.0, report[name]["failures"])
            self.assertEqual(report[name]["failures"], [])
        self.assertIs(report["amounts"]["exact"], True)
        self.assertIn("validate_packet", report)
        self.assertIn("available", report["validate_packet"])

    def test_citation_failures(self) -> None:
        packet = _packet()
        packet["sources"] = [
            {
                "id": "missing",
                "title": "Ausente",
                "path": "raw/documents/nope.md",
                "document_id": "law_bbbbbbbbbbbbbbbb",
                "pinpoints": ["linhas 1–2"],
            },
            {
                "id": "bad-path",
                "title": "Caminho",
                "path": "raw/documents/other.md",
                "document_id": "law_aaaaaaaaaaaaaaaa",
                "pinpoints": ["linhas 1–2"],
            },
            {
                "id": "far",
                "title": "Longe",
                "path": "raw/documents/example/2024/law_aaaaaaaaaaaaaaaa.md",
                "document_id": "law_aaaaaaaaaaaaaaaa",
                "pinpoints": ["linhas 50–60"],
            },
        ]
        packet["sections"]["fundamentacao_direito"] = [
            {
                "text": "Diz a fonte que «esta citação não consta do excerto legal».",
                "source_ids": ["far"],
            }
        ]
        report = evaluate(packet, self.catalog, self.retriever, None)
        citation = report["citation_existence"]
        self.assertLess(citation["ratio"], 1.0)
        text = " ".join(citation["failures"])
        self.assertIn("absent from catalog", text)
        self.assertIn("does not match catalog", text)
        self.assertIn("outside", text)
        self.assertIn("quote not in cited lines", text)

    def test_evidence_failures(self) -> None:
        packet = _packet()
        packet["evidence_matrix"][0]["basis"] = "unilateral_assertion"
        packet["sections"]["factos_provados"] = [
            {"text": "a) Facto.", "evidence_ids": ["n1"]}
        ]
        packet["sections"]["factos_nao_provados"] = [{"text": "aa) Sem prova."}]
        report = evaluate(packet, self.catalog, None, None)
        evidence = report["evidence_linkage"]
        self.assertLess(evidence["ratio"], 1.0)
        text = " ".join(evidence["failures"])
        self.assertIn("incompatible status/basis", text)
        self.assertIn("status not_proved", text)
        self.assertIn("needs evidence_ids", text)

    def test_amounts_and_sections_and_mentions_fail(self) -> None:
        packet = _packet()
        packet["amounts"] = [
            {"item": "Indemnização", "claimed": "10.00", "awarded": "12.00"}
        ]
        packet["decision_total"] = "10.00"
        packet["sections"]["sumario"] = [{"text": "1. Só um."}]
        packet["sections"]["saneador"] = []
        report = evaluate(
            packet,
            self.catalog,
            None,
            {"decision_total": "250.00", "must_mention": ["artigo 7.º", "circunstâncias extraordinárias"]},
        )
        self.assertLess(report["amounts"]["ratio"], 1.0)
        self.assertIs(report["amounts"]["exact"], False)
        self.assertLess(report["section_completeness"]["ratio"], 1.0)
        self.assertIn("sections.sumario has 1 points", " ".join(report["section_completeness"]["failures"]))
        self.assertIn("sections.saneador is empty", report["section_completeness"]["failures"])
        self.assertEqual(report["must_mention"]["ratio"], 0.5)
        self.assertTrue(any("circunstâncias extraordinárias" in item for item in report["must_mention"]["failures"]))

    def test_procedural_evidence_may_support_a_proved_fact(self) -> None:
        packet = _packet()
        packet["evidence_matrix"].append(
            {
                "id": "p1",
                "proposition": "A audiência realizou-se.",
                "status": "procedural",
                "basis": "procedural_record",
            }
        )
        packet["sections"]["factos_provados"].append(
            {"text": "b) Audiência.", "evidence_ids": ["p1"]}
        )
        report = evaluate(packet, self.catalog, None, None)
        self.assertEqual(report["evidence_linkage"]["ratio"], 1.0, report["evidence_linkage"]["failures"])

    def test_five_summary_points_pass(self) -> None:
        packet = _packet()
        packet["sections"]["sumario"] = [{"text": f"{index}. Ponto."} for index in range(1, 6)]
        report = evaluate(packet, self.catalog, None, None)
        self.assertEqual(report["section_completeness"]["ratio"], 1.0)


class CaseFileTests(unittest.TestCase):
    def test_twenty_case_files_match_the_schema(self) -> None:
        fictional = sorted(FICTIONAL.glob("*.json"))
        backtests = sorted(BACKTEST.glob("*.json"))
        self.assertEqual(len(fictional), 10, [path.name for path in fictional])
        self.assertEqual(len(backtests), 10, [path.name for path in backtests])
        seen_totals: set[str] = set()
        for path in fictional:
            self.assertRegex(path.name, r"^\d{2}-[a-z0-9-]+\.json$")
            case = json.loads(path.read_text(encoding="utf-8"))
            for field in ("id", "title", "record_text", "expected"):
                self.assertIn(field, case, path.name)
            self.assertTrue(str(case["title"]).strip())
            words = WORD.findall(case["record_text"])
            self.assertGreaterEqual(len(words), 300, path.name)
            self.assertLessEqual(len(words), 900, path.name)
            self.assertNotIn("Wizz", case["record_text"])
            expected = case["expected"]
            self._assert_expected_money(expected, path.name)
            self.assertIn(expected["outcome"], OUTCOMES, path.name)
            items = expected["awarded_items"]
            self.assertIsInstance(items, list)
            self.assertGreaterEqual(len(items), 1)
            total = Decimal("0.00")
            for item in items:
                self.assertIn("item", item)
                self.assertRegex(item["awarded"], MONEY.pattern)
                self.assertTrue(str(item["item"]).strip())
                total += Decimal(item["awarded"])
            self.assertEqual(total, Decimal(expected["decision_total"]), path.name)
            mentions = expected["must_mention"]
            self.assertIsInstance(mentions, list)
            self.assertGreaterEqual(len(mentions), 1)
            self.assertTrue(all(isinstance(item, str) and item.strip() for item in mentions))
            self.assertTrue(str(expected.get("notes") or "").strip(), path.name)
            seen_totals.add(expected["decision_total"])
            if expected["outcome"] == "procedente":
                self.assertTrue(all(Decimal(item["awarded"]) > 0 for item in items))
            if expected["outcome"] == "improcedente":
                self.assertEqual(Decimal(expected["decision_total"]), Decimal("0.00"))
        self.assertGreaterEqual(len(seen_totals), 8)

        seen_docs: set[str] = set()
        for path in backtests:
            self.assertRegex(path.name, r"^\d{2}\.json$")
            case = json.loads(path.read_text(encoding="utf-8"))
            for field in (
                "id",
                "document_id",
                "path",
                "title",
                "input_line_ranges",
                "expected_line_range",
                "expected",
            ):
                self.assertIn(field, case, path.name)
            self.assertRegex(case["document_id"], r"^law_[0-9a-f]{16}$")
            self.assertNotIn(case["document_id"], seen_docs)
            seen_docs.add(case["document_id"])
            self.assertTrue(case["path"].replace("\\", "/").endswith(case["document_id"] + ".md"))
            expected = case["expected"]
            self.assertRegex(expected["decision_total"], MONEY.pattern)
            self.assertIn(expected["outcome"], OUTCOMES)
            lines = _lines(case["path"])
            self.assertGreater(len(lines), 0)
            decision = case["expected_line_range"]
            self.assertEqual(len(decision), 2)
            self._assert_range(decision, len(lines), path.name)
            inputs = case["input_line_ranges"]
            self.assertIsInstance(inputs, list)
            self.assertGreaterEqual(len(inputs), 1)
            for item in inputs:
                self._assert_range(item, len(lines), path.name)
                self.assertFalse(_overlaps(item, decision), f"{path.name} input overlaps decision")
                self.assertLess(item[1], decision[0], path.name)
            head = lines[decision[0] - 1].casefold()
            self.assertTrue("decis" in head or "dispositivo" in head, head)
            body = _norm("\n".join(lines[decision[0] - 1 : decision[1]]))
            outcome = expected["outcome"]
            if outcome == "parcialmente procedente":
                self.assertIn("parcialmente procedente", body)
            elif outcome == "improcedente":
                self.assertIn("improcedente", body)
            else:
                stripped = body.replace("parcialmente procedente", "").replace("improcedente", "")
                self.assertIn("procedente", stripped)
            for literal in case.get("amount_literals", []):
                self.assertIn(_norm(literal), body, path.name)
            if expected["decision_total"] == "0.00":
                self.assertEqual(case.get("amount_literals") or [], [])

    def test_wizz_fixture_is_a_packet(self) -> None:
        path = ROOT / "app" / "eval" / "fixtures" / "packets" / "wizz-w4-5520-packet.json"
        packet = json.loads(path.read_text(encoding="utf-8"))
        for field in ("metadata", "policy", "sources", "evidence_matrix", "sections", "amounts", "decision_total"):
            self.assertIn(field, packet)
        self.assertEqual(packet["decision_total"], "615.34")

    def _assert_expected_money(self, expected: dict, label: str) -> None:
        self.assertRegex(expected["decision_total"], MONEY.pattern, label)

    def _assert_range(self, item: list[int], line_count: int, label: str) -> None:
        self.assertEqual(len(item), 2, label)
        start, end = item
        self.assertIsInstance(start, int)
        self.assertIsInstance(end, int)
        self.assertGreaterEqual(start, 1, label)
        self.assertLessEqual(end, line_count, label)
        self.assertLessEqual(start, end, label)


if __name__ == "__main__":
    unittest.main()
