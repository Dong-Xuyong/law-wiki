"""Offline tests for the draft worker."""

from __future__ import annotations

import json
import os
import unittest

from app.api.common import CSM_SENTENCE, MAX_PDF_BYTES, REQUIRED_SECTIONS
from app.api.deps import Services, set_services
from app.api.handler import handle as api_handle
from app.api.store import MemoryStore, set_store
from app.api.worker import handle as worker_handle
import app.api.worker as worker_module


class FakeRetriever:
    def catalog(self):
        return {"law_abc": {"path": "raw/x.md", "title": "Fonte", "rel_source": None}}

    def search(self, query, k=8, filters=None):
        return []

    def lines(self, document_id, line_start, line_end):
        return ""


class FakeLLM:
    def __init__(self):
        self.model_id = "fake-model"
        self.usage = {"inputTokens": 3, "outputTokens": 4}


def _api(method, path, body=None):
    event = {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": "user-1", "email": "judge@example.com"}}},
        },
    }
    if body is not None:
        event["body"] = json.dumps(body)
    response = api_handle(event, None)
    return response["statusCode"], json.loads(response["body"])


def _result(errors=None):
    paragraphs = []
    sections = {}
    for name in REQUIRED_SECTIONS:
        text = f"Texto {name}."
        paragraphs.append(
            {
                "id": f"{name}-0",
                "section": name,
                "index": 0,
                "text": text,
                "sourceIds": ["s1"],
                "evidenceIds": ["e1"] if "factos" in name else [],
                "confidence": "high",
                "note": "",
            }
        )
        sections[name] = [{"text": text, "align": "justify", "source_ids": ["s1"]}]
    return {
        "packet": {
            "metadata": {"document_title": "Minuta", "process_number": "não indicado"},
            "policy": {"strict_evidence": True},
            "sources": [
                {
                    "id": "s1",
                    "title": "Fonte",
                    "path": "raw/x.md",
                    "document_id": "law_abc",
                    "pinpoints": ["linha 1"],
                }
            ],
            "evidence_matrix": [
                {"id": "e1", "proposition": "Facto.", "status": "proved", "basis": "common"}
            ],
            "sections": sections,
            "amounts": [{"item": "Pedido", "claimed": "1.00", "awarded": "0.00", "reason": "teste"}],
            "decision_total": "0.00",
        },
        "paragraphs": paragraphs,
        "errors": list(errors or []),
        "audit": {
            "modelId": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "promptSha256": "abc123",
            "inputTokens": 11,
            "outputTokens": 7,
            "sourceIds": ["law_abc"],
        },
    }


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.calls = []
        self.extracted = []
        self.rendered = []
        self.services = Services(
            self.store,
            retriever_factory=lambda: FakeRetriever(),
            llm_factory=FakeLLM,
            draft_case=self._draft,
            extract_pdf_bytes=self._extract,
            validate_packet=lambda packet, *, catalog: [],
            render_docx=self._render,
        )
        set_services(self.services)
        set_store(None)
        self._saved = os.environ.get("LW_STATE_MACHINE_ARN")
        os.environ["LW_STATE_MACHINE_ARN"] = "arn:aws:states:eu-west-1:123:stateMachine:minutas"
        self._draft_error = None
        self._draft_errors = None

    def tearDown(self):
        set_services(None)
        set_store(None)
        if self._saved is None:
            os.environ.pop("LW_STATE_MACHINE_ARN", None)
        else:
            os.environ["LW_STATE_MACHINE_ARN"] = self._saved

    def _draft(self, record_text, *, llm, retriever, case_meta, input_record=None):
        self.calls.append(
            {
                "record_text": record_text,
                "case_meta": case_meta,
                "input_record": input_record,
                "model_id": llm.model_id,
            }
        )
        if self._draft_error is not None:
            raise self._draft_error
        return _result(self._draft_errors)

    def _extract(self, data, filename):
        self.extracted.append((data, filename))
        return {"text": "Texto extraído do PDF.", "manifest": {"pages": 2}}

    def _render(self, packet, *, template, out_docx, catalog):
        self.rendered.append(packet)
        out_docx.write_bytes(b"DOCX")
        return {}

    def _queue_text_case(self, text="Registo ficcional UNIQUE_RECORD_TOKEN."):
        status, body = _api(
            "POST",
            "/api/cases",
            {"title": "Caso ficcional", "inputKind": "text", "text": text, "fictional": True},
        )
        self.assertEqual(status, 201)
        case_id = body["case"]["caseId"]
        status, queued = _api("POST", f"/api/cases/{case_id}/drafts")
        self.assertEqual(status, 202)
        return case_id, queued["draftId"]

    def test_success_writes_packet_paragraphs_and_audit(self):
        case_id, draft_id = self._queue_text_case()
        seen = {}

        def draft(record_text, *, llm, retriever, case_meta, input_record=None):
            seen["status"] = self.store.get_item(f"DRAFT#{draft_id}", "META")["status"]
            self.calls.append(
                {"record_text": record_text, "case_meta": case_meta, "input_record": input_record}
            )
            return _result()

        self.services.draft_case = draft
        result = worker_handle({"caseId": case_id, "draftId": draft_id}, None)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(seen["status"], "running")
        self.assertEqual(self.calls[0]["record_text"], "Registo ficcional UNIQUE_RECORD_TOKEN.")
        self.assertIsNone(self.calls[0]["input_record"])
        self.assertEqual(self.calls[0]["case_meta"]["title"], "Caso ficcional")
        self.assertEqual(self.calls[0]["case_meta"]["process_number"], "não indicado")
        self.assertEqual(self.calls[0]["case_meta"]["place"], "")
        self.assertRegex(self.calls[0]["case_meta"]["draft_date"], r"^\d{4}-\d{2}-\d{2}$")

        meta = self.store.get_item(f"DRAFT#{draft_id}", "META")
        self.assertEqual(meta["status"], "ready")
        self.assertEqual(meta["modelId"], "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
        self.assertNotIn("error", meta)
        self.assertEqual(meta["totalCount"], len(REQUIRED_SECTIONS))
        summary = self.store.get_item(f"CASE#{case_id}", f"DRAFT#{draft_id}")
        self.assertEqual(summary["status"], "ready")
        packet = json.loads(self.store.get_bytes(f"drafts/{draft_id}/packet.json").decode("utf-8"))
        self.assertEqual(packet["decision_total"], "0.00")
        rows = self.store.query(f"DRAFT#{draft_id}", "PARA#")
        self.assertEqual(len(rows), len(REQUIRED_SECTIONS))
        self.assertTrue(all(row["review"]["status"] == "pending" for row in rows))
        self.assertEqual(rows[0]["originalText"], rows[0]["text"])
        self.assertTrue(rows[0]["SK"].startswith("PARA#"))
        audits = self.store.query(f"AUDIT#{draft_id}", "")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit["action"], "generate")
        self.assertEqual(audit["actor"], "user-1")
        self.assertEqual(audit["modelId"], "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
        self.assertEqual(audit["promptSha256"], "abc123")
        self.assertEqual(audit["sourceIds"], ["law_abc"])
        self.assertEqual(audit["inputTokens"], 11)
        self.assertEqual(audit["outputTokens"], 7)

        for row in rows:
            _api(
                "PATCH",
                f"/api/drafts/{draft_id}/paragraphs/{row['id']}",
                {"action": "accept"},
            )
        status, exported = _api("POST", f"/api/drafts/{draft_id}/export")
        self.assertEqual(status, 200)
        self.assertEqual(self.rendered[-1]["sections"]["decisao"][-1]["text"], CSM_SENTENCE)

    def test_draft_case_exception_is_recorded_without_raising(self):
        case_id, draft_id = self._queue_text_case()
        self._draft_error = RuntimeError("SECRET_CASE_TEXT should not be stored")
        with self.assertLogs("minutas.api", level="ERROR") as captured:
            result = worker_handle({"caseId": case_id, "draftId": draft_id}, None)
        self.assertEqual(result["status"], "failed")
        self.assertIn("RuntimeError", result["error"])
        self.assertNotIn("SECRET_CASE_TEXT", result["error"])
        meta = self.store.get_item(f"DRAFT#{draft_id}", "META")
        self.assertEqual(meta["status"], "failed")
        self.assertNotIn("SECRET_CASE_TEXT", meta["error"])
        blob = json.dumps(self.store.query(f"AUDIT#{draft_id}", ""))
        self.assertNotIn("SECRET_CASE_TEXT", blob)
        self.assertNotIn("SECRET_CASE_TEXT", "\n".join(captured.output))
        self.assertIsNone(self.store.get_bytes(f"drafts/{draft_id}/packet.json"))
        summary = self.store.get_item(f"CASE#{case_id}", f"DRAFT#{draft_id}")
        self.assertEqual(summary["status"], "failed")

    def test_validation_errors_save_packet_and_fail(self):
        case_id, draft_id = self._queue_text_case()
        self._draft_errors = ["missing citation"]
        result = worker_handle({"caseId": case_id, "draftId": draft_id}, None)
        self.assertEqual(result["status"], "failed")
        self.assertIn("missing citation", result["error"])
        meta = self.store.get_item(f"DRAFT#{draft_id}", "META")
        self.assertEqual(meta["status"], "failed")
        self.assertIn("missing citation", meta["error"])
        packet = json.loads(self.store.get_bytes(f"drafts/{draft_id}/packet.json").decode("utf-8"))
        self.assertIn("sumario", packet["sections"])
        self.assertEqual(len(self.store.query(f"DRAFT#{draft_id}", "PARA#")), len(REQUIRED_SECTIONS))
        audit = self.store.query(f"AUDIT#{draft_id}", "")[0]
        self.assertEqual(audit["action"], "generate")
        self.assertEqual(audit["promptSha256"], "abc123")

    def test_pdf_extract_and_size_limit(self):
        status, created = _api(
            "POST",
            "/api/cases",
            {"title": "PDF", "inputKind": "pdf", "fictional": True},
        )
        self.assertEqual(status, 201)
        case_id = created["case"]["caseId"]
        self.assertEqual(created["case"]["status"], "new")
        pdf = b"%PDF-1.4 fictional"
        self.store.put_bytes(f"cases/{case_id}/input.pdf", pdf, "application/pdf")
        status, queued = _api("POST", f"/api/cases/{case_id}/drafts")
        draft_id = queued["draftId"]
        result = worker_handle({"caseId": case_id, "draftId": draft_id}, None)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.extracted[0][0], pdf)
        self.assertEqual(self.extracted[0][1], "input.pdf")
        self.assertEqual(
            self.store.get_bytes(f"cases/{case_id}/input.txt").decode("utf-8"),
            "Texto extraído do PDF.",
        )
        self.assertEqual(self.calls[0]["input_record"]["kind"], "pdf")
        self.assertEqual(self.calls[0]["input_record"]["filename"], "input.pdf")
        self.assertEqual(self.calls[0]["input_record"]["pages"], 2)
        self.assertEqual(len(self.calls[0]["input_record"]["sha256"]), 64)
        case = self.store.get_item(f"USER#user-1", f"CASE#{case_id}")
        self.assertEqual(case["status"], "ready")

        self.extracted.clear()
        self.calls.clear()
        self.store.put_bytes(f"cases/{case_id}/input.txt", "já gravado".encode("utf-8"), "text/plain")
        status, queued = _api("POST", f"/api/cases/{case_id}/drafts")
        second = queued["draftId"]
        result = worker_handle({"caseId": case_id, "draftId": second}, None)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.extracted, [])
        self.assertEqual(self.calls[0]["record_text"], "já gravado")
        self.assertIsNone(self.calls[0]["input_record"])

        status, created = _api(
            "POST",
            "/api/cases",
            {"title": "Grande", "inputKind": "pdf", "fictional": True},
        )
        big_case = created["case"]["caseId"]
        self.store.put_bytes(f"cases/{big_case}/input.pdf", b"12345", "application/pdf")
        real_head = self.store.head

        def small_head(key):
            found = real_head(key)
            if found and key.endswith(".pdf"):
                return {"contentLength": 1, "contentType": "application/pdf"}
            return found

        self.store.head = small_head
        previous = worker_module.MAX_PDF_BYTES
        worker_module.MAX_PDF_BYTES = 4
        try:
            status, queued = _api("POST", f"/api/cases/{big_case}/drafts")
            self.extracted.clear()
            result = worker_handle({"caseId": big_case, "draftId": queued["draftId"]}, None)
        finally:
            worker_module.MAX_PDF_BYTES = previous
        self.assertEqual(result["status"], "failed")
        self.assertIn("15 MB", result["error"])
        self.assertEqual(self.extracted, [])
        self.assertEqual(self.store.get_item(f"USER#user-1", f"CASE#{big_case}")["status"], "new")
        self.assertGreater(MAX_PDF_BYTES, 4)

        self.store.head = real_head
        self.store.head = lambda key: (
            {"contentLength": MAX_PDF_BYTES + 1, "contentType": "application/pdf"}
            if key.endswith(".pdf")
            else real_head(key)
        )
        status, queued = _api("POST", f"/api/cases/{big_case}/drafts")
        self.extracted.clear()
        result = worker_handle({"caseId": big_case, "draftId": queued["draftId"]}, None)
        self.assertEqual(result["status"], "failed")
        self.assertIn("15 MB", result["error"])
        self.assertEqual(self.extracted, [])

    def test_missing_input_fails_closed(self):
        status, created = _api(
            "POST",
            "/api/cases",
            {"title": "Vazio", "inputKind": "pdf", "fictional": True},
        )
        case_id = created["case"]["caseId"]
        status, queued = _api("POST", f"/api/cases/{case_id}/drafts")
        result = worker_handle({"caseId": case_id, "draftId": queued["draftId"]}, None)
        self.assertEqual(result["status"], "failed")
        self.assertIn("missing", result["error"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
