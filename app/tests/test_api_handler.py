"""Offline route coverage for the Minutas HTTP API."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import unittest

import app.api.handler  # noqa: F401  (import must not pull engine modules)
from app.api.common import CSM_SENTENCE, REQUIRED_SECTIONS
from app.api.deps import Services, set_services
from app.api.handler import handle
from app.api.store import MemoryStore, set_store

ENGINE_AT_IMPORT = [name for name in sys.modules if name.startswith("app.engine.")]


def _claims(sub="user-1", email="judge@example.com"):
    return {"sub": sub, "email": email}


def invoke(method, path, *, body=None, claims=_claims(), query=None, raw_path=None, proxy=False, b64=False):
    event = {
        "version": "2.0",
        "requestContext": {"http": {"method": method, "path": path}},
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    if proxy:
        event["pathParameters"] = {"proxy": path.removeprefix("/api/").lstrip("/")}
    else:
        event["rawPath"] = raw_path or path
    if query is not None:
        event["queryStringParameters"] = {key: str(value) for key, value in query.items()}
    if body is not None:
        raw = json.dumps(body)
        if b64:
            event["body"] = base64.b64encode(raw.encode("utf-8")).decode("ascii")
            event["isBase64Encoded"] = True
        else:
            event["body"] = raw
    response = handle(event, None)
    if response["headers"].get("Content-Type") != "application/json":
        raise AssertionError(response["headers"])
    return response["statusCode"], json.loads(response["body"])


class FakeRetriever:
    def __init__(self):
        self.catalog_data = {
            "law_abc": {
                "path": "raw/documents/x.md",
                "title": "Fonte",
                "rel_source": None,
            }
        }
        self.searches = []
        self.line_calls = []

    def search(self, query, k=8, filters=None):
        self.searches.append((query, k, filters))
        return [
            {
                "document_id": "law_abc",
                "path": "raw/documents/x.md",
                "title": "Fonte",
                "line_start": 1,
                "line_end": 2,
                "text": "citação",
                "score": 1.0,
            }
        ]

    def lines(self, document_id, line_start, line_end):
        self.line_calls.append((document_id, line_start, line_end))
        if document_id not in self.catalog_data:
            raise KeyError(document_id)
        return "linha um\nlinha dois"

    def catalog(self):
        return self.catalog_data


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.retriever = FakeRetriever()
        self.rendered = []
        self.validated = []
        self.render_called = False
        self.services = Services(
            self.store,
            retriever_factory=lambda: self.retriever,
            validate_packet=self._validate,
            render_docx=self._render,
        )
        set_services(self.services)
        set_store(None)
        self._saved_env = {
            key: os.environ.get(key)
            for key in ("LW_STATE_MACHINE_ARN", "LW_TABLE", "LW_CASES_BUCKET", "LW_REGION")
        }
        os.environ["LW_STATE_MACHINE_ARN"] = "arn:aws:states:eu-west-1:123:stateMachine:minutas"
        os.environ["LW_TABLE"] = "minutas"
        os.environ["LW_CASES_BUCKET"] = "minutas-cases"
        os.environ["LW_REGION"] = "eu-west-1"

    def tearDown(self):
        set_services(None)
        set_store(None)
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _validate(self, packet, *, catalog):
        self.validated.append((packet, catalog))
        return []

    def _render(self, packet, *, template, out_docx, catalog):
        self.render_called = True
        self.rendered.append(packet)
        out_docx.parent.mkdir(parents=True, exist_ok=True)
        out_docx.write_bytes(b"DOCX-BYTES")
        return {"sources": []}

    def test_import_does_not_load_engine(self):
        self.assertEqual(ENGINE_AT_IMPORT, [])

    def test_me_and_proxy_and_stage_prefix(self):
        status, body = invoke("GET", "/api/me")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"sub": "user-1", "email": "judge@example.com"})

        status, body = invoke("GET", "/api/me", proxy=True)
        self.assertEqual(status, 200)
        self.assertEqual(body["sub"], "user-1")

        status, body = invoke("GET", "/api/me", raw_path="/prod/api/me/")
        self.assertEqual(status, 200)
        self.assertEqual(body["email"], "judge@example.com")

        status, body = invoke("GET", "/api/me", claims={"sub": "user-1"})
        self.assertEqual(body["email"], "")

    def test_every_route_requires_claims(self):
        routes = [
            ("GET", "/api/me", None),
            ("GET", "/api/cases", None),
            ("POST", "/api/cases", {"title": "A", "inputKind": "text", "text": "t", "fictional": True}),
            ("GET", "/api/cases/c_aaaaaaaaaa", None),
            ("POST", "/api/cases/c_aaaaaaaaaa/drafts", None),
            ("GET", "/api/drafts/d_aaaaaaaaaa", None),
            ("PATCH", "/api/drafts/d_aaaaaaaaaa/paragraphs/sumario-0", {"action": "accept"}),
            ("POST", "/api/drafts/d_aaaaaaaaaa/export", None),
            ("GET", "/api/search", None),
            ("GET", "/api/sources/law_abc/lines", None),
        ]
        for method, path, body in routes:
            query = {"q": "lei", "start": 1, "end": 2} if "search" in path or "lines" in path else None
            status, payload = invoke(method, path, body=body, claims=None, query=query)
            self.assertEqual(status, 401, path)
            self.assertEqual(payload["error"], "unauthorized")
            self.assertIn("message", payload)
        status, payload = invoke("GET", "/api/me", claims={"email": "a@b.c"})
        self.assertEqual(status, 401)
        status, payload = invoke("POST", "/api/me")
        self.assertEqual(status, 405)
        status, payload = invoke("GET", "/api/missing")
        self.assertEqual(status, 404)

    def test_create_case_validation(self):
        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "A", "inputKind": "text", "text": "t", "fictional": False},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "fictional_required")

        status, body = invoke("POST", "/api/cases", body={"title": "A", "inputKind": "text", "text": "t"})
        self.assertEqual(body["error"], "fictional_required")

        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "A", "inputKind": "text", "text": "t", "fictional": "true"},
        )
        self.assertEqual(body["error"], "fictional_required")

        event = {
            "version": "2.0",
            "rawPath": "/api/cases",
            "requestContext": {
                "http": {"method": "POST"},
                "authorizer": {"jwt": {"claims": _claims()}},
            },
            "body": "[1, 2]",
        }
        response = handle(event, None)
        payload = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(payload["error"], "invalid_body")

        event["body"] = "{"
        payload = json.loads(handle(event, None)["body"])
        self.assertEqual(payload["error"], "invalid_json")

        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "  ", "inputKind": "text", "text": "t", "fictional": True},
        )
        self.assertEqual(body["error"], "title_invalid")
        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "a" * 201, "inputKind": "text", "text": "t", "fictional": True},
        )
        self.assertEqual(body["error"], "title_invalid")
        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "Ok", "inputKind": "text", "fictional": True},
        )
        self.assertEqual(body["error"], "text_required")
        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "Ok", "inputKind": "text", "text": "x" * 200_001, "fictional": True},
        )
        self.assertEqual(body["error"], "text_too_long")
        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "Ok", "inputKind": "PDF", "fictional": True},
        )
        self.assertEqual(body["error"], "input_kind_invalid")

    def test_create_text_and_pdf_cases(self):
        status, body = invoke(
            "POST",
            "/api/cases",
            body={
                "title": "  Caso ficcional  ",
                "inputKind": "text",
                "text": "SEGREDO do processo",
                "fictional": True,
            },
            b64=True,
        )
        self.assertEqual(status, 201)
        self.assertNotIn("uploadUrl", body)
        self.assertNotIn("SEGREDO", json.dumps(body))
        case = body["case"]
        self.assertRegex(case["caseId"], r"^c_[a-z0-9]{10}$")
        self.assertEqual(case["title"], "Caso ficcional")
        self.assertEqual(case["inputKind"], "text")
        self.assertEqual(case["status"], "ready")
        self.assertRegex(case["createdAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$")
        stored = self.store.get_item(f"USER#user-1", f"CASE#{case['caseId']}")
        self.assertEqual(stored["owner"], "user-1")
        self.assertTrue(stored["fictional"])
        self.assertEqual(
            self.store.get_bytes(f"cases/{case['caseId']}/input.txt").decode("utf-8"),
            "SEGREDO do processo",
        )

        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "a" * 200, "inputKind": "pdf", "text": "SEGREDO", "fictional": True},
        )
        self.assertEqual(status, 201)
        pdf_case = body["case"]
        self.assertEqual(pdf_case["status"], "new")
        self.assertEqual(pdf_case["title"], "a" * 200)
        self.assertNotIn("SEGREDO", json.dumps(body))
        self.assertIsNone(self.store.get_bytes(f"cases/{pdf_case['caseId']}/input.txt"))
        signed = self.store.presign_puts[-1]
        self.assertEqual(signed["key"], f"cases/{pdf_case['caseId']}/input.pdf")
        self.assertEqual(signed["content_type"], "application/pdf")
        self.assertEqual(signed["expires_in"], 600)
        self.assertIn(f"cases/{pdf_case['caseId']}/input.pdf", body["uploadUrl"])
        self.assertIn("600", body["uploadUrl"])

        status, listed = invoke("GET", "/api/cases")
        self.assertEqual(status, 200)
        self.assertEqual(listed["items"][0]["caseId"], pdf_case["caseId"])
        self.assertEqual(listed["items"][1]["caseId"], case["caseId"])

        status, other = invoke("GET", "/api/cases", claims=_claims("user-2", "other@example.com"))
        self.assertEqual(other["items"], [])
        status, missing = invoke("GET", f"/api/cases/{case['caseId']}", claims=_claims("user-2"))
        self.assertEqual(status, 404)
        self.assertNotIn("Caso ficcional", json.dumps(missing))
        status, own = invoke("GET", f"/api/cases/{case['caseId']}")
        self.assertEqual(status, 200)
        self.assertEqual(own["case"]["caseId"], case["caseId"])
        self.assertEqual(own["drafts"], [])
        status, missing = invoke("GET", "/api/cases/not-an-id")
        self.assertEqual(status, 404)

    def test_start_draft_owner_and_execution(self):
        case_id = self._text_case()
        status, body = invoke("POST", f"/api/cases/{case_id}/drafts")
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "queued")
        self.assertRegex(body["draftId"], r"^d_[a-z0-9]{10}$")
        draft_id = body["draftId"]
        self.assertEqual(self.store.executions[0]["stateMachineArn"].endswith(":minutas"), True)
        self.assertEqual(self.store.executions[0]["input"], {"caseId": case_id, "draftId": draft_id})
        summary = self.store.get_item(f"CASE#{case_id}", f"DRAFT#{draft_id}")
        meta = self.store.get_item(f"DRAFT#{draft_id}", "META")
        self.assertEqual(summary["PK"], f"CASE#{case_id}")
        self.assertEqual(summary["status"], "queued")
        self.assertEqual(meta["SK"], "META")
        self.assertEqual(meta["owner"], "user-1")
        self.assertEqual(meta["packetKey"], f"drafts/{draft_id}/packet.json")

        status, fetched = invoke("GET", f"/api/cases/{case_id}")
        self.assertEqual(fetched["drafts"][0]["draftId"], draft_id)
        status, draft = invoke("GET", f"/api/drafts/{draft_id}")
        self.assertEqual(status, 200)
        self.assertEqual(draft["status"], "queued")
        self.assertEqual(draft["evidence"], [])
        self.assertIsNone(draft["decisionTotal"])
        self.assertNotIn("error", draft)
        self.assertEqual(draft["paragraphs"], [])

        status, denied = invoke("POST", f"/api/cases/{case_id}/drafts", claims=_claims("user-2"))
        self.assertEqual(status, 404)
        status, denied = invoke("GET", f"/api/drafts/{draft_id}", claims=_claims("user-2"))
        self.assertEqual(status, 404)
        self.assertNotIn(case_id, json.dumps(denied))

        self.store.start_error = RuntimeError("SECRET_SFN")
        status, failed = invoke("POST", f"/api/cases/{case_id}/drafts")
        self.assertEqual(status, 500)
        self.assertEqual(failed["error"], "workflow_start_failed")
        self.assertNotIn("SECRET_SFN", json.dumps(failed))
        failed_id = None
        for item in self.store.query(f"CASE#{case_id}", "DRAFT#"):
            if item["status"] == "failed":
                failed_id = item["draftId"]
        self.assertIsNotNone(failed_id)
        meta = self.store.get_item(f"DRAFT#{failed_id}", "META")
        self.assertEqual(meta["error"], "workflow_start_failed")
        self.assertNotIn("SECRET_SFN", json.dumps(meta))

        os.environ.pop("LW_STATE_MACHINE_ARN")
        before = len(self.store.query(f"CASE#{case_id}", "DRAFT#"))
        status, missing = invoke("POST", f"/api/cases/{case_id}/drafts")
        self.assertEqual(status, 500)
        self.assertEqual(missing["error"], "misconfigured")
        self.assertEqual(len(self.store.query(f"CASE#{case_id}", "DRAFT#")), before)

    def test_get_draft_assembles_packet(self):
        case_id, draft_id, _ids = self._seed_ready()
        status, body = invoke("GET", f"/api/drafts/{draft_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body["caseId"], case_id)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["modelId"], "fake-model")
        self.assertEqual(body["evidence"][0]["id"], "e1")
        self.assertEqual(body["sources"][0]["document_id"], "law_abc")
        self.assertEqual(body["amounts"][0]["awarded"], "0.00")
        self.assertEqual(body["decisionTotal"], "0.00")
        self.assertEqual(body["reviewedCount"], 0)
        self.assertEqual(body["totalCount"], len(REQUIRED_SECTIONS))
        self.assertNotIn("packetParagraph", body["paragraphs"][0])
        self.assertNotIn("PK", body["paragraphs"][0])

    def test_review_audit_and_export_gates(self):
        _case_id, draft_id, ids = self._seed_ready()
        status, queued = invoke("POST", f"/api/drafts/{draft_id}/export")
        # seeded draft is ready; unreviewed blocks first
        self.assertEqual(status, 409)
        self.assertEqual(queued["error"], "unreviewed")
        self.assertEqual(queued["remaining"], len(REQUIRED_SECTIONS))
        self.assertFalse(self.render_called)

        self.store.get_item  # keep store live
        meta = self.store.get_item(f"DRAFT#{draft_id}", "META")
        meta["status"] = "queued"
        self.store.put_item(meta)
        status, blocked = invoke("POST", f"/api/drafts/{draft_id}/export")
        self.assertEqual(blocked["error"], "not_ready")
        meta["status"] = "ready"
        self.store.put_item(meta)

        status, bad = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/{ids['sumario']}",
            body={"action": "edit", "text": "   "},
        )
        self.assertEqual(bad["error"], "text_required")
        status, bad = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/{ids['sumario']}",
            body={"action": "edit", "text": "x" * 20_001},
        )
        self.assertEqual(bad["error"], "text_too_long")
        status, bad = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/{ids['sumario']}",
            body={"action": "nope"},
        )
        self.assertEqual(bad["error"], "action_invalid")
        status, missing = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/sumario-9",
            body={"action": "accept"},
        )
        self.assertEqual(status, 404)
        status, denied = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/{ids['sumario']}",
            body={"action": "accept"},
            claims=_claims("user-2"),
        )
        self.assertEqual(status, 404)

        edited = "Texto revisto pelo juiz."
        status, paragraph = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/{ids['sumario']}",
            body={"action": "edit", "text": edited},
        )
        self.assertEqual(status, 200)
        self.assertEqual(paragraph["text"], edited)
        self.assertEqual(paragraph["originalText"], "Texto sumario.")
        self.assertEqual(paragraph["review"]["status"], "edited")
        self.assertEqual(paragraph["review"]["by"], "user-1")
        self.assertRegex(paragraph["review"]["at"], r"Z$")

        for name, paragraph_id in ids.items():
            if name == "sumario":
                continue
            action = "reject" if name == "decisao" else "accept"
            # decisao must stay non-empty, so accept it too; reject is covered below
            status, _body = invoke(
                "PATCH",
                f"/api/drafts/{draft_id}/paragraphs/{paragraph_id}",
                body={"action": "accept"},
            )
            self.assertEqual(status, 200)

        extra_id = "decisao-1"
        self._put_paragraph(draft_id, "decisao", 1, "Parágrafo a rejeitar.")
        status, rejected = invoke(
            "PATCH",
            f"/api/drafts/{draft_id}/paragraphs/{extra_id}",
            body={"action": "reject"},
        )
        self.assertEqual(rejected["review"]["status"], "rejected")

        status, draft = invoke("GET", f"/api/drafts/{draft_id}")
        self.assertEqual(draft["reviewedCount"], draft["totalCount"])

        audits = self.store.query(f"AUDIT#{draft_id}", "")
        actions = {item["action"] for item in audits}
        self.assertTrue({"edit", "accept", "reject"} <= actions)
        for item in audits:
            self.assertRegex(item["SK"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z#[a-z0-9]{4}$")
            self.assertEqual(item["actor"], "user-1")
            if item["action"] == "edit":
                self.assertEqual(item["textSha256"], hashlib.sha256(edited.encode("utf-8")).hexdigest())
                self.assertEqual(item["paragraphId"], ids["sumario"])
            if item["action"] in {"accept", "edit", "reject"}:
                self.assertIn("textSha256", item)

        self.services.validate_packet = lambda packet, *, catalog: ["citation missing"]
        status, invalid = invoke("POST", f"/api/drafts/{draft_id}/export")
        self.assertEqual(status, 422)
        self.assertEqual(invalid["error"], "invalid_packet")
        self.assertIn("citation missing", invalid["errors"])
        self.assertFalse(self.render_called)
        self.assertIsNone(self.store.get_bytes(f"exports/{draft_id}.docx"))

        self.services.validate_packet = self._validate
        status, exported = invoke("POST", f"/api/drafts/{draft_id}/export")
        self.assertEqual(status, 200)
        self.assertIn(f"exports/{draft_id}.docx", exported["url"])
        self.assertEqual(self.store.presign_gets[-1]["expires_in"], 600)
        self.assertEqual(self.store.get_bytes(f"exports/{draft_id}.docx"), b"DOCX-BYTES")
        packet = self.rendered[-1]
        decisao_texts = [item["text"] for item in packet["sections"]["decisao"]]
        self.assertEqual(decisao_texts[-1], CSM_SENTENCE)
        self.assertNotIn("Parágrafo a rejeitar.", decisao_texts)
        self.assertEqual(packet["sections"]["sumario"][0]["text"], edited)
        self.assertEqual(packet["sections"]["sumario"][0]["align"], "justify")
        self.assertEqual(self.validated[-1][0]["sections"]["decisao"][-1]["text"], CSM_SENTENCE)
        self.assertEqual(self.validated[-1][1]["law_abc"]["title"], "Fonte")
        export_audits = [item for item in self.store.query(f"AUDIT#{draft_id}", "") if item["action"] == "export"]
        self.assertEqual(len(export_audits), 1)
        self.assertEqual(export_audits[0]["actor"], "user-1")

        status, denied = invoke("POST", f"/api/drafts/{draft_id}/export", claims=_claims("user-2"))
        self.assertEqual(status, 404)

    def test_section_empty_before_render(self):
        _case_id, draft_id, ids = self._seed_ready()
        for name, paragraph_id in ids.items():
            action = "reject" if name == "sumario" else "accept"
            invoke(
                "PATCH",
                f"/api/drafts/{draft_id}/paragraphs/{paragraph_id}",
                body={"action": action},
            )
        status, body = invoke("POST", f"/api/drafts/{draft_id}/export")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "section_empty")
        self.assertEqual(body["section"], "sumario")
        self.assertIn("message", body)
        self.assertFalse(self.render_called)

    def test_failed_draft_can_still_export(self):
        _case_id, draft_id, ids = self._seed_ready(status="failed")
        for paragraph_id in ids.values():
            invoke(
                "PATCH",
                f"/api/drafts/{draft_id}/paragraphs/{paragraph_id}",
                body={"action": "accept"},
            )
        status, body = invoke("POST", f"/api/drafts/{draft_id}/export")
        self.assertEqual(status, 200)
        self.assertIn("url", body)
        self.assertEqual(self.rendered[-1]["sections"]["decisao"][-1]["text"], CSM_SENTENCE)

    def test_search_and_source_lines(self):
        status, body = invoke("GET", "/api/search")
        self.assertEqual(body["error"], "q_required")
        status, body = invoke("GET", "/api/search", query={"q": "   "})
        self.assertEqual(body["error"], "q_required")
        status, body = invoke("GET", "/api/search", query={"q": "lei", "k": "21"})
        self.assertEqual(body["error"], "k_invalid")
        status, body = invoke("GET", "/api/search", query={"q": "lei", "k": "0"})
        self.assertEqual(body["error"], "k_invalid")
        status, body = invoke("GET", "/api/search", query={"q": "lei", "k": "abc"})
        self.assertEqual(body["error"], "k_invalid")

        status, body = invoke("GET", "/api/search", query={"q": " responsabilidade ", "k": "20"})
        self.assertEqual(status, 200)
        self.assertEqual(body["items"][0]["document_id"], "law_abc")
        self.assertEqual(self.retriever.searches[-1][0], "responsabilidade")
        self.assertEqual(self.retriever.searches[-1][1], 20)

        status, body = invoke("GET", "/api/search", query={"q": "lei"})
        self.assertEqual(self.retriever.searches[-1][1], 8)

        status, body = invoke("GET", "/api/sources/law_missing/lines", query={"start": "1", "end": "2"})
        self.assertEqual(status, 404)
        self.assertEqual(self.retriever.line_calls, [])

        status, body = invoke("GET", "/api/sources/law_abc/lines", query={"start": "1", "end": "201"})
        self.assertEqual(body["error"], "too_many_lines")
        status, body = invoke("GET", "/api/sources/law_abc/lines", query={"start": "5", "end": "1"})
        self.assertEqual(body["error"], "range_invalid")
        status, body = invoke("GET", "/api/sources/law_abc/lines", query={"start": "0", "end": "1"})
        self.assertEqual(body["error"], "range_invalid")
        status, body = invoke("GET", "/api/sources/law_abc/lines")
        self.assertEqual(body["error"], "range_required")

        status, body = invoke("GET", "/api/sources/law_abc/lines", query={"start": "1", "end": "200"})
        self.assertEqual(status, 200)
        self.assertEqual(body["documentId"], "law_abc")
        self.assertEqual(body["title"], "Fonte")
        self.assertEqual(body["path"], "raw/documents/x.md")
        self.assertEqual(body["lineStart"], 1)
        self.assertEqual(body["lineEnd"], 200)
        self.assertEqual(body["text"], "linha um\nlinha dois")
        self.assertEqual(body["publicUrl"], "https://dong-xuyong.github.io/law-wiki/documents/law_abc/")
        self.assertEqual(self.retriever.line_calls[-1], ("law_abc", 1, 200))

    def _text_case(self) -> str:
        status, body = invoke(
            "POST",
            "/api/cases",
            body={"title": "Caso", "inputKind": "text", "text": "Registo ficcional.", "fictional": True},
        )
        self.assertEqual(status, 201)
        return body["case"]["caseId"]

    def _seed_ready(self, status="ready"):
        case_id = self._text_case()
        draft_id = "d_bbbbbbbbbb"
        stamp = "2026-10-16T10:00:00.000000Z"
        self.store.put_item(
            {
                "PK": f"CASE#{case_id}",
                "SK": f"DRAFT#{draft_id}",
                "draftId": draft_id,
                "caseId": case_id,
                "owner": "user-1",
                "status": status,
                "createdAt": stamp,
            }
        )
        self.store.put_item(
            {
                "PK": f"DRAFT#{draft_id}",
                "SK": "META",
                "draftId": draft_id,
                "caseId": case_id,
                "owner": "user-1",
                "status": status,
                "modelId": "fake-model",
                "packetKey": f"drafts/{draft_id}/packet.json",
                "reviewedCount": 0,
                "totalCount": len(REQUIRED_SECTIONS),
                "createdAt": stamp,
                "updatedAt": stamp,
            }
        )
        ids = {}
        sections = {}
        for index, name in enumerate(REQUIRED_SECTIONS):
            text = f"Texto {name}."
            ids[name] = f"{name}-0"
            self._put_paragraph(draft_id, name, 0, text)
            sections[name] = [
                {
                    "text": text,
                    "align": "justify",
                    "source_ids": ["s1"],
                    "evidence_ids": ["e1"] if "factos" in name else [],
                }
            ]
        packet = {
            "metadata": {"document_title": "Minuta", "process_number": "não indicado"},
            "policy": {"strict_evidence": True},
            "sources": [
                {
                    "id": "s1",
                    "title": "Fonte",
                    "path": "raw/documents/x.md",
                    "document_id": "law_abc",
                    "pinpoints": ["linha 1"],
                }
            ],
            "evidence_matrix": [
                {"id": "e1", "proposition": "Facto.", "status": "proved", "basis": "common"}
            ],
            "sections": sections,
            "amounts": [{"item": "Pedido", "claimed": "10.00", "awarded": "0.00", "reason": "sem prova"}],
            "decision_total": "0.00",
        }
        self.store.put_bytes(
            f"drafts/{draft_id}/packet.json",
            json.dumps(packet).encode("utf-8"),
            "application/json",
        )
        return case_id, draft_id, ids

    def _put_paragraph(self, draft_id, section, index, text):
        paragraph_id = f"{section}-{index}"
        self.store.put_item(
            {
                "PK": f"DRAFT#{draft_id}",
                "SK": f"PARA#{paragraph_id}",
                "id": paragraph_id,
                "section": section,
                "index": index,
                "text": text,
                "originalText": text,
                "sourceIds": ["s1"],
                "evidenceIds": ["e1"] if "factos" in section else [],
                "confidence": "high",
                "note": "",
                "review": {"status": "pending", "by": "", "at": ""},
                "packetParagraph": {
                    "text": text,
                    "align": "justify",
                    "source_ids": ["s1"],
                    "evidence_ids": ["e1"] if "factos" in section else [],
                },
            }
        )


if __name__ == "__main__":
    unittest.main()
