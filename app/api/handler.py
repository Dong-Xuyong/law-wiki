"""HTTP API payload v2 router for Minutas.

Entry point: `handle(event, context)`. Owner is the JWT `sub` claim. Case
record text is stored in S3 and is never written to logs.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

from app.api.common import (
    CSM_SENTENCE,
    DEFAULT_SEARCH_K,
    MAX_PARAGRAPH_CHARS,
    MAX_RECORD_CHARS,
    MAX_SEARCH_K,
    MAX_SOURCE_LINES,
    MAX_TITLE_CHARS,
    PRESIGN_SECONDS,
    PUBLIC_DOCUMENT_URL,
    REQUIRED_SECTIONS,
    REVIEW_STATUS_FOR_ACTION,
    REVIEWED_STATUSES,
    ApiError,
    new_public_id,
    now_iso,
    output_docx_path,
    paragraph_sort_key,
    sha256_text,
    sync_draft_summary,
    template_path,
    write_audit,
)
from app.api.deps import get_services

logger = logging.getLogger("minutas.api")

_CASE_ID = re.compile(r"^c_[a-z0-9]{10}$")
_DRAFT_ID = re.compile(r"^d_[a-z0-9]{10}$")
_API_PREFIX = re.compile(r"(?:^|/)api(?=/|$)")

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def handle(event: dict, context: object) -> dict:
    del context
    try:
        return _dispatch(event or {})
    except ApiError as exc:
        body = {"error": exc.code, "message": exc.message, **exc.extra}
        return _response(exc.status, body)
    except Exception as exc:
        logger.error("unhandled kind=%s", type(exc).__name__)
        return _response(500, {"error": "internal", "message": "Internal error"})


def _dispatch(event: dict) -> dict:
    method = _method(event)
    path = _api_path(event)
    claims = _claims(event)
    if claims is None:
        raise ApiError(401, "unauthorized", "Authentication required")
    sub = str(claims["sub"])
    email = str(claims.get("email") or "")
    parts = [unquote(part) for part in path.split("/") if part]
    query = event.get("queryStringParameters") or {}

    if parts == ["me"] and method == "GET":
        return _response(200, {"sub": sub, "email": email})
    if parts == ["cases"] and method == "GET":
        return _list_cases(sub)
    if parts == ["cases"] and method == "POST":
        return _create_case(sub, _read_json(event))
    if len(parts) == 2 and parts[0] == "cases" and method == "GET":
        return _get_case(sub, parts[1])
    if len(parts) == 3 and parts[0] == "cases" and parts[2] == "drafts" and method == "POST":
        return _start_draft(sub, parts[1])
    if len(parts) == 2 and parts[0] == "drafts" and method == "GET":
        return _get_draft(sub, parts[1])
    if (
        len(parts) == 4
        and parts[0] == "drafts"
        and parts[2] == "paragraphs"
        and method == "PATCH"
    ):
        return _patch_paragraph(sub, parts[1], parts[3], _read_json(event))
    if len(parts) == 3 and parts[0] == "drafts" and parts[2] == "export" and method == "POST":
        return _export(sub, parts[1])
    if parts == ["search"] and method == "GET":
        return _search(query)
    if len(parts) == 3 and parts[0] == "sources" and parts[2] == "lines" and method == "GET":
        return _source_lines(parts[1], query)
    if _known_path(parts):
        raise ApiError(405, "method_not_allowed", "Method not allowed")
    raise ApiError(404, "not_found", "Route not found")


def _list_cases(sub: str) -> dict:
    store = get_services().repository()
    items = [_public_case(item) for item in store.query(f"USER#{sub}", "CASE#")]
    items.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
    return _response(200, {"items": items})


def _create_case(sub: str, body: dict) -> dict:
    if body.get("fictional") is not True:
        raise ApiError(400, "fictional_required", "fictional must be true")
    title = body.get("title")
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= MAX_TITLE_CHARS):
        raise ApiError(400, "title_invalid", "title must be 1 to 200 characters")
    title = title.strip()
    kind = body.get("inputKind")
    if kind not in ("text", "pdf"):
        raise ApiError(400, "input_kind_invalid", "inputKind must be text or pdf")
    text = body.get("text")
    if text is not None and not isinstance(text, str):
        raise ApiError(400, "text_invalid", "text must be a string")
    if isinstance(text, str) and len(text) > MAX_RECORD_CHARS:
        raise ApiError(400, "text_too_long", "text must be at most 200000 characters")
    if kind == "text" and (not isinstance(text, str) or text.strip() == ""):
        raise ApiError(400, "text_required", "text is required when inputKind is text")

    store = get_services().repository()
    case_id = new_public_id("c_")
    stamp = now_iso()
    status = "ready" if kind == "text" else "new"
    input_key = f"cases/{case_id}/input.txt" if kind == "text" else f"cases/{case_id}/input.pdf"
    item = {
        "PK": f"USER#{sub}",
        "SK": f"CASE#{case_id}",
        "caseId": case_id,
        "owner": sub,
        "title": title,
        "inputKind": kind,
        "status": status,
        "createdAt": stamp,
        "updatedAt": stamp,
        "inputKey": input_key,
        "fictional": True,
    }
    store.put_item(item)
    payload: dict[str, Any] = {"case": _public_case(item)}
    if kind == "text":
        store.put_bytes(input_key, text.encode("utf-8"), "text/plain; charset=utf-8")
    else:
        payload["uploadUrl"] = store.presign_put(
            f"cases/{case_id}/input.pdf",
            "application/pdf",
            PRESIGN_SECONDS,
        )
    return _response(201, payload)


def _get_case(sub: str, case_id: str) -> dict:
    case = _require_case(sub, case_id)
    store = get_services().repository()
    drafts = []
    for item in store.query(f"CASE#{case_id}", "DRAFT#"):
        drafts.append(
            {
                "draftId": item["draftId"],
                "status": item.get("status"),
                "createdAt": item.get("createdAt"),
            }
        )
    drafts.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
    return _response(200, {"case": _public_case(case), "drafts": drafts})


def _start_draft(sub: str, case_id: str) -> dict:
    _require_case(sub, case_id)
    arn = os.environ.get("LW_STATE_MACHINE_ARN")
    if not arn:
        raise ApiError(500, "misconfigured", "Draft workflow is not configured")
    store = get_services().repository()
    draft_id = new_public_id("d_")
    stamp = now_iso()
    summary = {
        "PK": f"CASE#{case_id}",
        "SK": f"DRAFT#{draft_id}",
        "draftId": draft_id,
        "caseId": case_id,
        "owner": sub,
        "status": "queued",
        "createdAt": stamp,
    }
    meta = {
        "PK": f"DRAFT#{draft_id}",
        "SK": "META",
        "draftId": draft_id,
        "caseId": case_id,
        "owner": sub,
        "status": "queued",
        "modelId": "",
        "packetKey": f"drafts/{draft_id}/packet.json",
        "reviewedCount": 0,
        "totalCount": 0,
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    store.put_item(summary)
    store.put_item(meta)
    try:
        store.start_execution(arn, {"caseId": case_id, "draftId": draft_id})
    except Exception as exc:
        logger.error("start_execution_failed kind=%s", type(exc).__name__)
        meta["status"] = "failed"
        meta["error"] = "workflow_start_failed"
        meta["updatedAt"] = now_iso()
        store.put_item(meta)
        sync_draft_summary(store, meta)
        raise ApiError(500, "workflow_start_failed", "Draft could not be queued") from None
    return _response(202, {"draftId": draft_id, "status": "queued"})


def _get_draft(sub: str, draft_id: str) -> dict:
    meta = _require_draft(sub, draft_id)
    store = get_services().repository()
    paragraphs = _load_paragraphs(store, draft_id)
    packet = _load_packet(store, draft_id)
    reviewed = sum(1 for item in paragraphs if _review_status(item) in REVIEWED_STATUSES)
    decision_total = None
    evidence: list = []
    sources: list = []
    amounts: list = []
    if packet is not None:
        evidence = list(packet.get("evidence_matrix") or packet.get("evidence") or [])
        sources = list(packet.get("sources") or [])
        amounts = list(packet.get("amounts") or [])
        if "decision_total" in packet:
            decision_total = packet.get("decision_total")
        elif "decisionTotal" in packet:
            decision_total = packet.get("decisionTotal")
    body: dict[str, Any] = {
        "draftId": meta["draftId"],
        "caseId": meta["caseId"],
        "status": meta.get("status"),
        "modelId": meta.get("modelId") or "",
        "createdAt": meta.get("createdAt"),
        "evidence": evidence,
        "sources": sources,
        "amounts": amounts,
        "decisionTotal": decision_total,
        "paragraphs": [_public_paragraph(item) for item in paragraphs],
        "reviewedCount": reviewed,
        "totalCount": len(paragraphs),
    }
    if meta.get("error"):
        body["error"] = meta["error"]
    return _response(200, body)


def _patch_paragraph(sub: str, draft_id: str, paragraph_id: str, body: dict) -> dict:
    meta = _require_draft(sub, draft_id)
    action = body.get("action")
    if action not in REVIEW_STATUS_FOR_ACTION:
        raise ApiError(400, "action_invalid", "action must be accept, edit, or reject")
    store = get_services().repository()
    item = store.get_item(f"DRAFT#{draft_id}", f"PARA#{paragraph_id}")
    if item is None:
        raise ApiError(404, "not_found", "Paragraph not found")
    if action == "edit":
        text = body.get("text")
        if not isinstance(text, str) or text.strip() == "":
            raise ApiError(400, "text_required", "edit requires non-empty text")
        if len(text) > MAX_PARAGRAPH_CHARS:
            raise ApiError(400, "text_too_long", "text must be at most 20000 characters")
        item["text"] = text
        packet_paragraph = dict(item.get("packetParagraph") or {})
        packet_paragraph["text"] = text
        item["packetParagraph"] = packet_paragraph
    review_status = REVIEW_STATUS_FOR_ACTION[action]
    item["review"] = {"status": review_status, "by": sub, "at": now_iso()}
    store.put_item(item)
    paragraphs = _load_paragraphs(store, draft_id)
    meta["reviewedCount"] = sum(1 for row in paragraphs if _review_status(row) in REVIEWED_STATUSES)
    meta["totalCount"] = len(paragraphs)
    meta["updatedAt"] = now_iso()
    store.put_item(meta)
    write_audit(
        store,
        draft_id,
        sub,
        action,
        paragraphId=paragraph_id,
        textSha256=sha256_text(str(item.get("text") or "")),
    )
    return _response(200, _public_paragraph(item))


def _export(sub: str, draft_id: str) -> dict:
    meta = _require_draft(sub, draft_id)
    if meta.get("status") in ("queued", "running"):
        raise ApiError(409, "not_ready", "Draft is not ready to export")
    store = get_services().repository()
    paragraphs = _load_paragraphs(store, draft_id)
    remaining = sum(1 for item in paragraphs if _review_status(item) not in REVIEWED_STATUSES)
    if remaining:
        raise ApiError(
            409,
            "unreviewed",
            f"{remaining} paragraphs still pending review",
            remaining=remaining,
        )
    packet = _load_packet(store, draft_id)
    if packet is None:
        raise ApiError(409, "not_ready", "Draft packet is not available")
    export_packet = _build_export_packet(packet, paragraphs)
    services = get_services()
    retriever = services.retriever()
    catalog = retriever.catalog()
    errors = services.run_validate(export_packet, catalog=catalog)
    if errors:
        raise ApiError(
            422,
            "invalid_packet",
            "Draft packet failed validation",
            errors=[str(item) for item in errors],
        )
    out = output_docx_path(draft_id)
    services.run_render(
        export_packet,
        template=template_path(),
        out_docx=out,
        catalog=catalog,
    )
    if not out.is_file():
        raise ApiError(500, "render_failed", "DOCX was not produced")
    data = out.read_bytes()
    try:
        out.unlink()
    except OSError:
        logger.error("tmp_cleanup_failed")
    key = f"exports/{draft_id}.docx"
    store.put_bytes(key, data, DOCX_CONTENT_TYPE)
    write_audit(store, draft_id, sub, "export")
    url = store.presign_get(key, PRESIGN_SECONDS)
    return _response(200, {"url": url})


def _search(query: dict) -> dict:
    raw_q = query.get("q")
    if not isinstance(raw_q, str) or raw_q.strip() == "":
        raise ApiError(400, "q_required", "q is required")
    k = _parse_k(query.get("k"))
    try:
        items = get_services().retriever().search(raw_q.strip(), k=k)
    except Exception as exc:
        logger.error("search_failed kind=%s", type(exc).__name__)
        raise ApiError(500, "search_failed", "Search failed") from None
    return _response(200, {"items": list(items or [])})


def _source_lines(document_id: str, query: dict) -> dict:
    if not document_id or "/" in document_id or document_id in {".", ".."}:
        raise ApiError(404, "not_found", "Source not found")
    if "start" not in query or "end" not in query:
        raise ApiError(400, "range_required", "start and end are required")
    start = _parse_positive_int(query.get("start"), "start")
    end = _parse_positive_int(query.get("end"), "end")
    if end < start:
        raise ApiError(400, "range_invalid", "end must be greater than or equal to start")
    if end - start + 1 > MAX_SOURCE_LINES:
        raise ApiError(400, "too_many_lines", "A request can return at most 200 lines")
    retriever = get_services().retriever()
    catalog = retriever.catalog() or {}
    entry = catalog.get(document_id)
    if not isinstance(entry, dict):
        raise ApiError(404, "not_found", "Source not found")
    try:
        text = retriever.lines(document_id, start, end)
    except KeyError:
        raise ApiError(404, "not_found", "Source not found") from None
    except Exception as exc:
        logger.error("lines_failed kind=%s", type(exc).__name__)
        raise ApiError(500, "lines_failed", "Source lines could not be read") from None
    return _response(
        200,
        {
            "documentId": document_id,
            "title": entry.get("title") or "",
            "path": entry.get("path") or "",
            "lineStart": start,
            "lineEnd": end,
            "text": text if isinstance(text, str) else str(text),
            "publicUrl": PUBLIC_DOCUMENT_URL.format(document_id=document_id),
        },
    )


def _build_export_packet(packet: dict, paragraphs: list[dict]) -> dict:
    grouped: dict[str, list] = {name: [] for name in REQUIRED_SECTIONS}
    extras: dict[str, list] = {}
    for item in sorted(paragraphs, key=paragraph_sort_key):
        if _review_status(item) == "rejected":
            continue
        section = str(item.get("section") or "")
        rendered = _to_packet_paragraph(item)
        if section in grouped:
            grouped[section].append(rendered)
        elif section:
            extras.setdefault(section, []).append(rendered)
    for name in REQUIRED_SECTIONS:
        if not grouped[name]:
            raise ApiError(
                409,
                "section_empty",
                f"Section {name} is empty after review",
                section=name,
            )
    sections: dict[str, list] = {}
    for name in REQUIRED_SECTIONS:
        sections[name] = grouped[name]
    for name, rows in extras.items():
        sections[name] = rows
    sections["decisao"] = list(sections["decisao"]) + [{"text": CSM_SENTENCE}]
    exported = dict(packet)
    exported["sections"] = sections
    return exported


def _to_packet_paragraph(item: dict) -> dict:
    base = dict(item.get("packetParagraph") or {})
    for key in (
        "id",
        "section",
        "index",
        "confidence",
        "note",
        "originalText",
        "review",
        "sourceIds",
        "evidenceIds",
        "PK",
        "SK",
    ):
        base.pop(key, None)
    base["text"] = item.get("text") or ""
    if item.get("sourceIds") is not None:
        base["source_ids"] = list(item.get("sourceIds") or [])
    if item.get("evidenceIds") is not None:
        base["evidence_ids"] = list(item.get("evidenceIds") or [])
    return base


def _require_case(sub: str, case_id: str) -> dict:
    if not _CASE_ID.match(case_id or ""):
        raise ApiError(404, "not_found", "Case not found")
    store = get_services().repository()
    item = store.get_item(f"USER#{sub}", f"CASE#{case_id}")
    if item is None or item.get("owner") != sub:
        raise ApiError(404, "not_found", "Case not found")
    return item


def _require_draft(sub: str, draft_id: str) -> dict:
    if not _DRAFT_ID.match(draft_id or ""):
        raise ApiError(404, "not_found", "Draft not found")
    store = get_services().repository()
    meta = store.get_item(f"DRAFT#{draft_id}", "META")
    if meta is None or meta.get("owner") != sub:
        raise ApiError(404, "not_found", "Draft not found")
    return meta


def _load_paragraphs(store: Any, draft_id: str) -> list[dict]:
    rows = store.query(f"DRAFT#{draft_id}", "PARA#")
    rows.sort(key=paragraph_sort_key)
    return rows


def _load_packet(store: Any, draft_id: str) -> dict | None:
    raw = store.get_bytes(f"drafts/{draft_id}/packet.json")
    if raw is None:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _public_case(item: dict) -> dict:
    return {
        "caseId": item["caseId"],
        "title": item["title"],
        "inputKind": item["inputKind"],
        "status": item["status"],
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
    }


def _public_paragraph(item: dict) -> dict:
    try:
        index = int(item.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    review = item.get("review") or {"status": "pending", "by": "", "at": ""}
    return {
        "id": item.get("id"),
        "section": item.get("section"),
        "index": index,
        "text": item.get("text") or "",
        "sourceIds": list(item.get("sourceIds") or []),
        "evidenceIds": list(item.get("evidenceIds") or []),
        "confidence": item.get("confidence") or "medium",
        "note": item.get("note") or "",
        "originalText": item.get("originalText") if item.get("originalText") is not None else item.get("text") or "",
        "review": {
            "status": review.get("status") or "pending",
            "by": review.get("by") or "",
            "at": review.get("at") or "",
        },
    }


def _review_status(item: dict) -> str:
    review = item.get("review") or {}
    return str(review.get("status") or "pending")


def _known_path(parts: list[str]) -> bool:
    if parts == ["me"]:
        return True
    if parts == ["cases"]:
        return True
    if len(parts) == 2 and parts[0] == "cases":
        return True
    if len(parts) == 3 and parts[0] == "cases" and parts[2] == "drafts":
        return True
    if len(parts) == 2 and parts[0] == "drafts":
        return True
    if len(parts) == 4 and parts[0] == "drafts" and parts[2] == "paragraphs":
        return True
    if len(parts) == 3 and parts[0] == "drafts" and parts[2] == "export":
        return True
    if parts == ["search"]:
        return True
    if len(parts) == 3 and parts[0] == "sources" and parts[2] == "lines":
        return True
    return False


def _method(event: dict) -> str:
    http = (event.get("requestContext") or {}).get("http") or {}
    method = http.get("method") or event.get("httpMethod") or ""
    return str(method).upper()


def _api_path(event: dict) -> str:
    raw = event.get("rawPath") or ""
    if not raw:
        proxy = (event.get("pathParameters") or {}).get("proxy")
        if proxy:
            raw = "/api/" + str(proxy).lstrip("/")
        else:
            http = (event.get("requestContext") or {}).get("http") or {}
            raw = str(http.get("path") or "")
    match = _API_PREFIX.search(raw)
    if match is None:
        return "/"
    rest = raw[match.end() :]
    if not rest.startswith("/"):
        rest = "/" + rest
    if len(rest) > 1 and rest.endswith("/"):
        rest = rest[:-1]
    return rest


def _claims(event: dict) -> dict | None:
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    jwt = authorizer.get("jwt") or {}
    claims = jwt.get("claims")
    if not isinstance(claims, dict):
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str) or sub.strip() == "":
        return None
    return claims


def _read_json(event: dict) -> dict:
    body = event.get("body")
    if body is None or body == "":
        raise ApiError(400, "invalid_body", "JSON body required")
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "invalid_body", "Body is not valid base64 JSON") from None
    if not isinstance(body, str):
        raise ApiError(400, "invalid_body", "JSON body required")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        raise ApiError(400, "invalid_json", "Body is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise ApiError(400, "invalid_body", "JSON object required")
    return parsed


def _parse_k(raw: object) -> int:
    if raw is None or raw == "":
        return DEFAULT_SEARCH_K
    if isinstance(raw, bool):
        raise ApiError(400, "k_invalid", "k must be an integer from 1 to 20")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().lstrip("+").isdigit():
        value = int(raw.strip())
    else:
        raise ApiError(400, "k_invalid", "k must be an integer from 1 to 20")
    if value < 1 or value > MAX_SEARCH_K:
        raise ApiError(400, "k_invalid", "k must be an integer from 1 to 20")
    return value


def _parse_positive_int(raw: object, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ApiError(400, "range_invalid", f"{name} must be a positive integer")
    if isinstance(raw, str) and not raw.strip().lstrip("+").isdigit():
        raise ApiError(400, "range_invalid", f"{name} must be a positive integer")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "range_invalid", f"{name} must be a positive integer") from None
    if value < 1:
        raise ApiError(400, "range_invalid", f"{name} must be a positive integer")
    return value


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _response(status: int, payload: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, ensure_ascii=False, default=_json_default),
    }

