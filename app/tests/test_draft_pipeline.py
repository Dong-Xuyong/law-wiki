"""Offline tests for the Minutas drafting pipeline and Bedrock request shape."""

from __future__ import annotations

import io
import json
import os
import re
import sys
import types
import unittest
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from app.engine.draft.cli import main
from app.engine.draft.fakes import FakeLLM, FakeRetriever
from app.engine.draft.llm import (
    TOOL_DESCRIPTION,
    TOOL_NAME,
    BedrockLLM,
    parse_converse_output,
)
from app.engine.draft.pipeline import _strip_failed_quotes, draft_case
from app.engine.draft.prompts import SYSTEM


LAW_SENTENCE = "O artigo 7.º fixa 250 euros até 1500 quilómetros."
LAW_ID = "law_aaaaaaaaaaaaaaaa"
CASE_ID = "law_bbbbbbbbbbbbbbbb"

DOC_LAW = "\n".join(
    [
        "Regulamento (CE) n.º 261/2004, artigo 5.º, artigo 6.º, artigo 7.º, artigo 8.º e artigo 9.º.",
        "Cancelamento, atraso, circunstâncias extraordinárias, assistência, reencaminhamento e reembolso.",
        "Indemnização por atraso igual ou superior a três horas, bandas de distância de 1500 e 3500 quilómetros.",
        LAW_SENTENCE,
    ]
)
DOC_CASE = "\n".join(
    [
        "A jurisprudência Sturgeon e Nelson trata o atraso igual ou superior a três horas como compensação do Regulamento (CE) n.º 261/2004.",
        "As circunstâncias extraordinárias podem excluir a indemnização do artigo 7.º quando provadas, sem afastar a assistência do artigo 9.º.",
    ]
)

CASE_META = {
    "title": "Wizz Air W4 5520",
    "process_number": "não indicado",
    "place": "Lisboa",
    "draft_date": "2026-10-16",
}

INPUT_RECORD = {
    "kind": "pdf",
    "filename": "caso.pdf",
    "sha256": "ab" * 32,
    "pages": 1,
    "extracted_text": "input-record.txt",
    "manifest": "input-manifest.json",
    "classification": "User-supplied factual/procedural record; not a Law Wiki legal authority",
}


def corpus() -> FakeRetriever:
    return FakeRetriever(
        [
            {
                "document_id": LAW_ID,
                "path": "raw/documents/demo/law_aaaaaaaaaaaaaaaa.md",
                "title": "Regulamento 261 artigos",
                "text": DOC_LAW,
                "rel_source": None,
                "kind": "legislation",
            },
            {
                "document_id": CASE_ID,
                "path": "raw/documents/demo/law_bbbbbbbbbbbbbbbb.md",
                "title": "Sturgeon Nelson atraso",
                "text": DOC_CASE,
                "rel_source": None,
                "kind": "case_law",
            },
        ]
    )


def matter_payload() -> dict[str, Any]:
    return {
        "parties": [
            {"role": "reclamante", "name_in_record": ""},
            {"role": "reclamada", "name_in_record": "Wizz Air"},
        ],
        "claimant_name": "",
        "respondent_name": "Wizz Air",
        "claims": [
            {"description": "Indemnização do artigo 7.º", "amount": "600.00"},
            {"description": "Despesa de lounge", "amount": "10.50"},
        ],
        "chronology": ["10 de janeiro de 2024: voo programado."],
        "flight": {
            "carrier": "Wizz Air",
            "number": "W4 5520",
            "origin": "Porto",
            "destination": "Milão",
            "date": "2024-01-10",
            "scheduled_departure": "09:30",
            "scheduled_arrival": "12:55",
        },
        "issues": ["reembolso do bilhete e compensação por atraso"],
        "limitations": ["distância não medida no processo", "anexo não examinado"],
    }


def evidence_payload() -> dict[str, Any]:
    return {
        "evidence_matrix": [
            {
                "id": "f01",
                "proposition": "O litígio respeita ao voo W4 5520 Porto–Milão em 10 de janeiro de 2024.",
                "status": "proved",
                "basis": "common",
            },
            {
                "id": "f02",
                "proposition": "A distância ortodrómica é de 1488 km.",
                "status": "not_proved",
                "basis": "unilateral_assertion",
            },
            {
                "id": "f03",
                "proposition": "A reclamante apresentou reclamação e alterou o pedido em audiência.",
                "status": "procedural",
                "basis": "procedural_record",
            },
            {
                "id": "f04",
                "proposition": "O anexo da transportadora prova o reembolso invocado.",
                "status": "not_proved",
                "basis": "unseen_attachment",
            },
        ]
    }


def _source_ids(user: str) -> list[str]:
    return re.findall(r"(?m)^ID_FONTE: (\S+)\s*$", user)


def base_sections(source_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    primary = source_ids[0]
    contrary = source_ids[-1]
    return {
        "sumario": [
            {
                "text": "A indemnização padronizada depende dos excertos locais sobre o artigo 7.º.",
                "source_ids": [primary],
            },
            {
                "text": "O atraso igual ou superior a três horas lê-se nos excertos que citam Sturgeon e Nelson.",
                "source_ids": [contrary],
            },
            {
                "text": "Circunstâncias extraordinárias só relevam quando o excerto as exige provadas.",
                "source_ids": [contrary],
            },
            {
                "text": "Despesas e distâncias que o registo não demonstra ficam por provar.",
                "source_ids": [primary],
            },
        ],
        "relatorio": [
            {
                "text": (
                    "A reclamante pediu indemnização e depois indicou despesas. "
                    "A reclamada foi notificada. Não se escreve número de processo que o caso não traga."
                )
            }
        ],
        "objeto_litigio": [
            {
                "text": (
                    "Importa decidir se há indemnização padronizada e se as despesas "
                    "indicadas entram no montante, dentro do que estiver provado."
                )
            }
        ],
        "saneador": [
            {
                "text": (
                    "O registo não fixa competência nem data de audiência para além "
                    "do que descreve como acto processual. Nada se presume."
                )
            }
        ],
        "factos_provados": [
            {
                "text": "O litígio respeita ao voo W4 5520 Porto–Milão em 10 de janeiro de 2024.",
                "evidence_ids": ["f01"],
            },
            {
                "text": "A reclamante apresentou reclamação e alterou o pedido em audiência.",
                "evidence_ids": ["f03"],
            },
        ],
        "factos_nao_provados": [
            {
                "text": "Que a distância ortodrómica seja de 1488 km.",
                "evidence_ids": ["f02"],
            },
            {
                "text": "Que o anexo da transportadora prove o reembolso invocado.",
                "evidence_ids": ["f04"],
            },
        ],
        "motivacao": [
            {
                "text": (
                    f"A matriz separa o que é comum do que é só alegado. «{LAW_SENTENCE}» "
                    "O anexo não examinado não prova o seu conteúdo."
                ),
                "source_ids": [primary],
            }
        ],
        "fundamentacao_direito": [
            {
                "text": (
                    "Os excertos admitem indemnização padronizada em atraso longo e, "
                    "em sentido contrário, excluem-na quando as circunstâncias extraordinárias "
                    "estão provadas. Não se aplica banda de distância que o registo não demonstra."
                ),
                "source_ids": [primary, contrary] if contrary != primary else [primary],
            }
        ],
        "decisao": [
            {
                "text": (
                    "Julga-se o pedido parcialmente procedente, nos limites do que "
                    "ficou provado, sem criar pagamentos omissos no registo."
                )
            }
        ],
    }


def base_amounts() -> list[dict[str, str]]:
    return [
        {
            "item": "Indemnização do artigo 7.º",
            "claimed": "600.00",
            "awarded": "900.00",
            "reason": "O modelo pediu acima do valor reclamado.",
        },
        {
            "item": "Lounge",
            "claimed": "10,50",
            "awarded": "3,25",
            "reason": "Parcial e não integralmente provado.",
        },
    ]


def draft_response(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    del system, schema
    return {"sections": base_sections(_source_ids(user)), "amounts": base_amounts()}


def scripted_llm(**overrides: Any) -> FakeLLM:
    responses: dict[str, Any] = {
        "matter": matter_payload(),
        "evidence": evidence_payload(),
        "research": {"queries": ["reembolso do voo W4 5520"]},
        "draft": draft_response,
        "repair": {},
    }
    responses.update(overrides)
    return FakeLLM(responses, input_tokens=100, output_tokens=40)


def run_case(
    *,
    draft: Any = None,
    evidence: Any = None,
    max_repairs: int = 2,
    input_record: dict[str, Any] | None = INPUT_RECORD,
    repair: Any = None,
) -> tuple[dict[str, Any], FakeLLM, FakeRetriever]:
    overrides: dict[str, Any] = {}
    if draft is not None:
        overrides["draft"] = draft
    if evidence is not None:
        overrides["evidence"] = evidence
    if repair is not None:
        overrides["repair"] = repair
    llm = scripted_llm(**overrides)
    retriever = corpus()
    result = draft_case(
        "Registo fictício do voo W4 5520. A reclamante não se identifica pelo nome.",
        llm=llm,
        retriever=retriever,
        case_meta=CASE_META,
        input_record=input_record,
        max_repairs=max_repairs,
    )
    return result, llm, retriever


def _validate_importable() -> bool:
    try:
        from app.engine.validate import validate_packet
    except ImportError:
        return False
    return callable(validate_packet)


@contextmanager
def installed_validator(errors: list[str]):
    counter = {"n": 0}

    def validate_packet(packet: dict[str, Any], *, catalog: dict[str, Any]) -> list[str]:
        del packet
        if not isinstance(catalog, dict):
            return ["catalog"]
        counter["n"] += 1
        return list(errors)

    module = types.ModuleType("app.engine.validate")
    module.validate_packet = validate_packet
    module.counter = counter
    previous = sys.modules.get("app.engine.validate")
    sys.modules["app.engine.validate"] = module
    try:
        yield module
    finally:
        if previous is None:
            sys.modules.pop("app.engine.validate", None)
        else:
            sys.modules["app.engine.validate"] = previous


class DraftPipelineTests(unittest.TestCase):
    def test_system_prompt_encodes_strict_evidence_and_section_order(self) -> None:
        self.assertIn("português de Portugal", SYSTEM)
        self.assertIn("unilateral_assertion", SYSTEM)
        self.assertIn("unseen_attachment", SYSTEM)
        self.assertIn("Não inventes", SYSTEM)
        for key in (
            "sumario",
            "factos_provados",
            "factos_nao_provados",
            "fundamentacao_direito",
            "decisao",
        ):
            self.assertIn(key, SYSTEM)

    def test_happy_path_structure(self) -> None:
        result, llm, retriever = run_case(max_repairs=0)
        packet = result["packet"]
        paragraphs = result["paragraphs"]

        self.assertEqual(
            [call["step"] for call in llm.calls],
            ["matter", "evidence", "research", "draft"],
        )
        self.assertGreaterEqual(len(retriever.searches), 4)
        self.assertLessEqual(len(retriever.searches), 8)
        self.assertTrue(all(item["k"] == 6 for item in retriever.searches))
        joined = " ".join(item["query"] for item in retriever.searches).casefold()
        self.assertIn("261", joined)
        self.assertIn("sturgeon", joined)
        self.assertIn("artigo 8", joined)

        self.assertEqual(packet["metadata"]["process_number"], "não indicado")
        self.assertEqual(packet["metadata"]["claimant"], "Reclamante não identificada")
        self.assertEqual(packet["metadata"]["respondent"], "Wizz Air")
        self.assertEqual(packet["metadata"]["document_title"], "Minuta \u2014 Wizz Air W4 5520")
        self.assertEqual(packet["metadata"]["draft_date"], "2026-10-16")
        self.assertEqual(
            packet["metadata"]["place_and_date"],
            "Lisboa, 16 de outubro de 2026",
        )
        self.assertIs(packet["policy"]["strict_evidence"], True)
        self.assertEqual(packet["input_record"], INPUT_RECORD)
        for forbidden in ("judge", "judge_name", "arbitrator", "signature"):
            self.assertNotIn(forbidden, packet["metadata"])
        self.assertNotRegex(json.dumps(packet, ensure_ascii=False), r"https?://|file://")

        self.assertEqual(packet["amounts"][0]["awarded"], "600.00")
        self.assertEqual(packet["amounts"][0]["claimed"], "600.00")
        self.assertIn("limitado ao pedido", packet["amounts"][0]["reason"])
        self.assertEqual(packet["amounts"][1]["claimed"], "10.50")
        self.assertEqual(packet["amounts"][1]["awarded"], "3.25")
        self.assertEqual(packet["decision_total"], "603.25")
        self.assertEqual(packet["metadata"]["case_value"], "610.50")
        awarded = sum(Decimal(row["awarded"]) for row in packet["amounts"])
        claimed = sum(Decimal(row["claimed"]) for row in packet["amounts"])
        self.assertEqual(Decimal(packet["decision_total"]), awarded)
        self.assertEqual(Decimal(packet["metadata"]["case_value"]), claimed)
        for row in packet["amounts"]:
            self.assertLessEqual(Decimal(row["awarded"]), Decimal(row["claimed"]))
            self.assertRegex(row["awarded"], r"^\d+\.\d{2}$")
            self.assertRegex(row["claimed"], r"^\d+\.\d{2}$")

        decision_text = " ".join(spec["text"] for spec in packet["sections"]["decisao"])
        self.assertIn("603.25", decision_text)
        self.assertIn("610.50", decision_text)
        self.assertIn("16 de outubro de 2026", decision_text)
        self.assertTrue(packet["sections"]["factos_provados"][0]["text"].startswith("a) "))
        self.assertTrue(packet["sections"]["factos_provados"][1]["text"].startswith("b) "))
        self.assertTrue(packet["sections"]["factos_nao_provados"][0]["text"].startswith("aa) "))
        self.assertTrue(packet["sections"]["factos_nao_provados"][1]["text"].startswith("bb) "))
        self.assertEqual(len(packet["sections"]["sumario"]), 4)
        self.assertTrue(packet["sources"])
        for section in ("sumario", "motivacao", "fundamentacao_direito"):
            for spec in packet["sections"][section]:
                self.assertTrue(spec.get("source_ids"), section)

        self.assertEqual(len(paragraphs), sum(len(packet["sections"][key]) for key in packet["sections"]))
        for paragraph in paragraphs:
            self.assertEqual(paragraph["id"], f"{paragraph['section']}-{paragraph['index']}")
            self.assertIn(paragraph["confidence"], {"high", "medium", "low"})
            self.assertTrue(paragraph["note"])
            spec = packet["sections"][paragraph["section"]][paragraph["index"]]
            self.assertEqual(paragraph["text"], spec["text"])
            self.assertEqual(paragraph["sourceIds"], list(spec.get("source_ids") or []))
            self.assertEqual(paragraph["evidenceIds"], list(spec.get("evidence_ids") or []))

        motivacao = next(item for item in paragraphs if item["section"] == "motivacao")
        self.assertIn(f"«{LAW_SENTENCE}»", motivacao["text"])
        self.assertEqual(motivacao["confidence"], "high")
        unproved = [item for item in paragraphs if item["section"] == "factos_nao_provados"]
        self.assertTrue(unproved)
        self.assertTrue(all(item["confidence"] == "low" for item in unproved))
        self.assertIn("não provado", unproved[0]["note"])

        self.assertEqual(result["audit"]["modelId"], "fake-model")
        self.assertRegex(result["audit"]["promptSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["audit"]["inputTokens"], 400)
        self.assertEqual(result["audit"]["outputTokens"], 160)
        self.assertEqual(
            result["audit"]["sourceIds"],
            [source["id"] for source in packet["sources"]],
        )
        again, _, _ = run_case(max_repairs=0)
        self.assertEqual(result["audit"]["promptSha256"], again["audit"]["promptSha256"])

    def test_happy_path_validates_when_engine_validate_exists(self) -> None:
        if not _validate_importable():
            self.skipTest(
                "app.engine.validate ainda não importável; não se afirma errors==[]."
            )
        result, _, _ = run_case(max_repairs=2)
        self.assertEqual(result["errors"], [])

    def test_fabricated_quote_is_downgraded(self) -> None:
        def draft(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
            payload = draft_response(system, user, schema)
            payload["sections"]["fundamentacao_direito"][0]["text"] = (
                "«O modelo inventou um pagamento de 9999 euros não constante do excerto.» "
                "“pagamento inventado de 7777 euros” "
                '"pagamento inventado de 8888 euros"'
            )
            return payload

        result, _, _ = run_case(draft=draft, max_repairs=0)
        law = next(
            item for item in result["paragraphs"] if item["section"] == "fundamentacao_direito"
        )
        self.assertEqual(law["confidence"], "low")
        self.assertIn("Citação não verificada", law["note"])
        for mark in ("«", "»", "“", "”", '"'):
            self.assertNotIn(mark, law["text"])
        self.assertIn("9999", law["text"])
        self.assertIn("7777", law["text"])
        self.assertIn("8888", law["text"])
        motivacao = next(item for item in result["paragraphs"] if item["section"] == "motivacao")
        self.assertIn(f"«{LAW_SENTENCE}»", motivacao["text"])
        self.assertEqual(motivacao["confidence"], "high")

    def test_unknown_source_id_is_removed(self) -> None:
        def draft(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
            payload = draft_response(system, user, schema)
            payload["sections"]["fundamentacao_direito"][0]["source_ids"].append(
                "fonte-fantasma"
            )
            return payload

        result, _, _ = run_case(draft=draft, max_repairs=0)
        packet = result["packet"]
        self.assertNotIn("fonte-fantasma", json.dumps(packet, ensure_ascii=False))
        law = next(
            item for item in result["paragraphs"] if item["section"] == "fundamentacao_direito"
        )
        self.assertNotIn("fonte-fantasma", law["sourceIds"])
        self.assertTrue(law["sourceIds"])
        self.assertEqual(law["confidence"], "low")
        self.assertIn("Fonte alheia aos excertos foi removida", law["note"])
        known = {source["id"] for source in packet["sources"]}
        for paragraph in result["paragraphs"]:
            self.assertTrue(set(paragraph["sourceIds"]) <= known)

    def test_unilateral_assertion_cannot_remain_proved(self) -> None:
        def evidence(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
            del system, user, schema
            payload = evidence_payload()
            payload["evidence_matrix"][0]["status"] = "proved"
            payload["evidence_matrix"][0]["basis"] = "unilateral_assertion"
            return payload

        result, _, _ = run_case(evidence=evidence, max_repairs=0)
        item = next(
            entry
            for entry in result["packet"]["evidence_matrix"]
            if entry["id"] == "f01"
        )
        self.assertEqual(item["status"], "not_proved")
        self.assertEqual(item["basis"], "unilateral_assertion")
        proved = result["packet"]["sections"]["factos_provados"][0]
        self.assertNotIn("f01", proved.get("evidence_ids") or [])

    def test_repair_loop_stops_at_max_repairs(self) -> None:
        queue = [{"sections": {"sumario": [{"text": "1. Texto de reparação."}]}} for _ in range(3)]
        with installed_validator(["erro persistente"]) as module:
            result, llm, _ = run_case(repair=queue, max_repairs=2)
        self.assertEqual(module.counter["n"], 3)
        self.assertEqual([call["step"] for call in llm.calls].count("repair"), 2)
        self.assertEqual(len(queue), 1)
        self.assertEqual(result["errors"], ["erro persistente"])
        self.assertTrue(result["paragraphs"])
        self.assertTrue(all(item["confidence"] == "low" for item in result["paragraphs"]))
        self.assertIn("Reparação automática", result["paragraphs"][0]["note"])

        queue_zero = [{"sections": {"sumario": [{"text": "1. Não deve ser consumido."}]}}]
        with installed_validator(["erro persistente"]) as module:
            result, llm, _ = run_case(repair=queue_zero, max_repairs=0)
        self.assertEqual(module.counter["n"], 1)
        self.assertEqual([call["step"] for call in llm.calls].count("repair"), 0)
        self.assertEqual(len(queue_zero), 1)
        self.assertEqual(result["errors"], ["erro persistente"])
        self.assertNotIn("Reparação automática", result["paragraphs"][0]["note"])

    def test_fake_retriever_quote_is_whitespace_exact(self) -> None:
        retriever = corpus()
        self.assertEqual(retriever.lines(LAW_ID, 4, 4), LAW_SENTENCE)
        self.assertTrue(
            retriever.verify_quote(
                LAW_ID,
                4,
                4,
                "O artigo  7.º fixa 250 euros até 1500 quilómetros.",
            )
        )
        self.assertFalse(
            retriever.verify_quote(
                LAW_ID,
                4,
                4,
                "O artigo 7.º fixa 250 euros ate 1500 quilometros.",
            )
        )
        cleaned, failed = _strip_failed_quotes(
            "Antes “citação curva inventada” depois.",
            lambda quote: False,
        )
        self.assertTrue(failed)
        self.assertNotIn("“", cleaned)
        self.assertNotIn("”", cleaned)
        self.assertIn("citação curva inventada", cleaned)

    def test_cli_refuses_without_live(self) -> None:
        stdout = io.StringIO()
        with patch("sys.stdout", stdout), patch(
            "boto3.client", side_effect=AssertionError("bedrock")
        ):
            code = main(
                ["--record", "record.txt", "--index", "index.sqlite3", "--out", "packet.json"]
            )
        self.assertEqual(code, 2)
        text = stdout.getvalue()
        self.assertIn("--live", text)
        self.assertIn("Bedrock", text)


class BedrockLLMTests(unittest.TestCase):
    def test_model_and_region_defaults(self) -> None:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"LW_MODEL_ID", "LW_REGION"}
        }
        with patch.dict(os.environ, env, clear=True):
            llm = BedrockLLM()
        self.assertEqual(llm.model_id, "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
        self.assertEqual(llm.region, "eu-west-1")
        self.assertEqual(llm.usage, {"inputTokens": 0, "outputTokens": 0})
        with patch.dict(
            os.environ,
            {"LW_MODEL_ID": "from-env", "LW_REGION": "eu-north-1"},
        ):
            from_env = BedrockLLM()
            explicit = BedrockLLM(model_id="explicit", region="eu-west-1")
        self.assertEqual(from_env.model_id, "from-env")
        self.assertEqual(from_env.region, "eu-north-1")
        self.assertEqual(explicit.model_id, "explicit")
        self.assertEqual(explicit.region, "eu-west-1")

    def test_converse_forces_emit_tool(self) -> None:
        import boto3
        from botocore.stub import Stubber

        self.assertEqual(TOOL_NAME, "emit")
        model_id = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
        region = "eu-west-1"
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        stubber = Stubber(client)
        first_schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        second_schema = {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        }
        stubber.add_response(
            "converse",
            _converse_response({"ok": True}, 10, 4),
            _expected_request("sistema", "utilizador", first_schema, 8000, model_id),
        )
        stubber.add_response(
            "converse",
            _converse_response({"n": 2}, 3, 1),
            _expected_request("sistema-2", "utilizador-2", second_schema, 120, model_id),
        )
        stubber.activate()
        try:
            with patch("app.engine.draft.llm.boto3.client", return_value=client) as mocked:
                llm = BedrockLLM(model_id=model_id, region=region)
                first = llm.complete_json("sistema", "utilizador", first_schema)
                second = llm.complete_json(
                    "sistema-2",
                    "utilizador-2",
                    second_schema,
                    max_tokens=120,
                )
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(mocked.call_args.args, ("bedrock-runtime",))
            kwargs = mocked.call_args.kwargs
            self.assertEqual(kwargs["region_name"], region)
            self.assertEqual(kwargs["config"].read_timeout, 300)
            self.assertEqual(kwargs["config"].retries.get("mode"), "adaptive")
        finally:
            stubber.deactivate()
        stubber.assert_no_pending_responses()
        self.assertEqual(first, {"ok": True})
        self.assertEqual(second, {"n": 2})
        self.assertEqual(llm.usage, {"inputTokens": 13, "outputTokens": 5})

    def test_parse_string_tool_input_and_missing_tool(self) -> None:
        parsed = parse_converse_output(
            {
                "output": {
                    "message": {
                        "content": [
                            {"toolUse": {"name": "emit", "input": '{"ok": true}'}}
                        ]
                    }
                }
            }
        )
        self.assertEqual(parsed, {"ok": True})
        with self.assertRaises(RuntimeError):
            parse_converse_output({"output": {"message": {"content": [{"text": "livre"}]}}})
        self.assertTrue(TOOL_DESCRIPTION)


def _expected_request(
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int,
    model_id: str,
) -> dict[str, Any]:
    return {
        "modelId": model_id,
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.0},
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": "emit",
                        "description": TOOL_DESCRIPTION,
                        "inputSchema": {"json": schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": "emit"}},
        },
    }


def _converse_response(payload: dict[str, Any], input_tokens: int, output_tokens: int) -> dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tooluse_test",
                            "name": "emit",
                            "input": payload,
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        },
        "metrics": {"latencyMs": 5},
    }


if __name__ == "__main__":
    unittest.main()
