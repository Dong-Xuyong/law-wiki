"""Step Functions draft worker.

Entry point: `handle(event, context)` with `{"caseId", "draftId"}`. Failures
are written onto the draft meta item. The handler does not raise after that,
and it never logs case text.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.api.common import (
    MAX_PDF_BYTES,
    WorkerError,
    concise,
    now_iso,
    sha256_bytes,
    sync_draft_summary,
    today_iso,
    write_audit,
)
from app.api.deps import get_services

logger = logging.getLogger("minutas.api")

_INPUT_CLASSIFICATION = (
    "User-supplied factual/procedural record; not a Law Wiki legal authority"
)


def handle(event: dict, context: object) -> dict:
    del context
    event = event or {}
    draft_id = event.get("draftId")
    case_id = event.get("caseId")
    try:
        return _run(str(case_id or ""), str(draft_id or ""))
    except Exception as exc:
        message = exc.message if isinstance(exc, WorkerError) else f"draft_failed:{type(exc).__name__}"
        logger.error("draft_failed draftId=%s kind=%s", draft_id, type(exc).__name__)
        _mark_failed(str(draft_id or ""), message, actor=None)
        return {"draftId": draft_id, "caseId": case_id, "status": "failed", "error": message}


def _run(case_id: str, draft_id: str) -> dict:
    if not case_id or not draft_id:
        raise WorkerError("caseId and draftId are required")
    services = get_services()
    store = services.repository()
    meta = store.get_item(f"DRAFT#{draft_id}", "META")
    if meta is None:
        raise WorkerError("Draft not found")
    if meta.get("caseId") != case_id:
        raise WorkerError("Draft does not belong to this case")
    _set_status(store, meta, "running")
    case = store.get_item(f"USER#{meta['owner']}", f"CASE#{case_id}")
    if case is None:
        raise WorkerError("Case not found")
    record_text, input_record = _load_record(store, services, case)
    _mark_case_ready(store, case)
    retriever = services.retriever()
    llm = services.llm()
    case_meta = {
        "title": case.get("title") or "",
        "process_number": case.get("processNumber") or case.get("process_number") or "não indicado",
        "place": case.get("place") or "",
        "draft_date": today_iso(),
    }
    try:
        result = services.run_draft(
            record_text,
            llm=llm,
            retriever=retriever,
            case_meta=case_meta,
            input_record=input_record,
        )
    except WorkerError:
        raise
    except Exception as exc:
        logger.error("draft_case_failed draftId=%s kind=%s", draft_id, type(exc).__name__)
        raise WorkerError(f"draft_failed:{type(exc).__name__}") from None
    if not isinstance(result, dict):
        raise WorkerError("draft_failed:invalid_result")
    packet = result.get("packet") if isinstance(result.get("packet"), dict) else None
    if packet is not None:
        _save_packet(store, draft_id, packet)
    paragraphs = _paragraph_items(draft_id, result.get("paragraphs") or [], packet)
    if paragraphs:
        store.put_items(paragraphs)
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
    model_id = str(audit.get("modelId") or getattr(llm, "model_id", "") or "")
    errors = [str(item) for item in (result.get("errors") or []) if str(item).strip()]
    meta = store.get_item(f"DRAFT#{draft_id}", "META") or meta
    meta["modelId"] = model_id
    meta["totalCount"] = len(paragraphs)
    meta["reviewedCount"] = 0
    meta["packetKey"] = f"drafts/{draft_id}/packet.json"
    usage = getattr(llm, "usage", None) or {}
    input_tokens = audit.get("inputTokens", usage.get("inputTokens", 0))
    output_tokens = audit.get("outputTokens", usage.get("outputTokens", 0))
    source_ids = list(audit.get("sourceIds") or [])
    prompt_sha = audit.get("promptSha256") or ""
    actor = str(meta.get("owner") or "")
    if errors:
        message = concise("validation: " + "; ".join(errors))
        meta["status"] = "failed"
        meta["error"] = message
        meta["updatedAt"] = now_iso()
        store.put_item(meta)
        sync_draft_summary(store, meta)
        write_audit(
            store,
            draft_id,
            actor,
            "generate",
            modelId=model_id,
            promptSha256=prompt_sha,
            sourceIds=source_ids,
            inputTokens=input_tokens,
            outputTokens=output_tokens,
        )
        return {"draftId": draft_id, "caseId": case_id, "status": "failed", "error": message}
    meta.pop("error", None)
    meta["status"] = "ready"
    meta["updatedAt"] = now_iso()
    store.put_item(meta)
    sync_draft_summary(store, meta)
    write_audit(
        store,
        draft_id,
        actor,
        "generate",
        modelId=model_id,
        promptSha256=prompt_sha,
        sourceIds=source_ids,
        inputTokens=input_tokens,
        outputTokens=output_tokens,
    )
    return {"draftId": draft_id, "caseId": case_id, "status": "ready"}


def _load_record(store: Any, services: Any, case: dict) -> tuple[str, dict | None]:
    case_id = case["caseId"]
    text_key = f"cases/{case_id}/input.txt"
    pdf_key = f"cases/{case_id}/input.pdf"
    existing = store.get_bytes(text_key)
    if existing is not None:
        try:
            record_text = existing.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkerError("input_not_utf8") from exc
        if record_text.strip() == "":
            raise WorkerError("Case input is empty")
        return record_text, None
    head = store.head(pdf_key)
    if head is None:
        raise WorkerError("Case input is missing")
    if int(head.get("contentLength") or 0) > MAX_PDF_BYTES:
        raise WorkerError("PDF exceeds 15 MB")
    data = store.get_bytes(pdf_key)
    if data is None:
        raise WorkerError("Case input is missing")
    if len(data) > MAX_PDF_BYTES:
        raise WorkerError("PDF exceeds 15 MB")
    extracted = services.extract_pdf(data, "input.pdf")
    if not isinstance(extracted, dict) or not isinstance(extracted.get("text"), str):
        raise WorkerError("PDF extraction failed")
    record_text = extracted["text"]
    if record_text.strip() == "":
        raise WorkerError("Case input is empty")
    store.put_bytes(text_key, record_text.encode("utf-8"), "text/plain; charset=utf-8")
    manifest = extracted.get("manifest") if isinstance(extracted.get("manifest"), dict) else {}
    input_record: dict[str, Any] = {
        "kind": "pdf",
        "filename": "input.pdf",
        "sha256": sha256_bytes(data),
        "classification": _INPUT_CLASSIFICATION,
        "manifest": manifest,
    }
    if "pages" in manifest:
        input_record["pages"] = manifest["pages"]
    return record_text, input_record


def _mark_case_ready(store: Any, case: dict) -> None:
    if case.get("status") == "ready":
        return
    case["status"] = "ready"
    case["updatedAt"] = now_iso()
    case["inputKey"] = f"cases/{case['caseId']}/input.txt"
    store.put_item(case)


def _save_packet(store: Any, draft_id: str, packet: dict) -> None:
    raw = json.dumps(packet, ensure_ascii=False).encode("utf-8")
    store.put_bytes(f"drafts/{draft_id}/packet.json", raw, "application/json")


def _paragraph_items(draft_id: str, paragraphs: list, packet: dict | None) -> list[dict]:
    items: list[dict] = []
    for raw in paragraphs:
        if not isinstance(raw, dict):
            continue
        section = str(raw.get("section") or "")
        try:
            index = int(raw.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        paragraph_id = str(raw.get("id") or f"{section}-{index}")
        text = str(raw.get("text") or "")
        packet_paragraph = _packet_paragraph(packet, section, index, text)
        items.append(
            {
                "PK": f"DRAFT#{draft_id}",
                "SK": f"PARA#{paragraph_id}",
                "id": paragraph_id,
                "section": section,
                "index": index,
                "text": text,
                "originalText": text,
                "sourceIds": list(raw.get("sourceIds") or []),
                "evidenceIds": list(raw.get("evidenceIds") or []),
                "confidence": raw.get("confidence") or "medium",
                "note": raw.get("note") or "",
                "review": {"status": "pending", "by": "", "at": ""},
                "packetParagraph": packet_paragraph,
            }
        )
    return items


def _packet_paragraph(packet: dict | None, section: str, index: int, text: str) -> dict:
    sections = (packet or {}).get("sections") or {}
    rows = sections.get(section) or []
    if isinstance(rows, list) and 0 <= index < len(rows) and isinstance(rows[index], dict):
        return dict(rows[index])
    return {"text": text}


def _set_status(store: Any, meta: dict, status: str) -> dict:
    meta["status"] = status
    meta["updatedAt"] = now_iso()
    store.put_item(meta)
    sync_draft_summary(store, meta)
    return meta


def _mark_failed(draft_id: str, message: str, actor: str | None) -> None:
    if not draft_id:
        return
    try:
        store = get_services().repository()
        meta = store.get_item(f"DRAFT#{draft_id}", "META")
        if meta is None:
            return
        meta["status"] = "failed"
        meta["error"] = concise(message)
        meta["updatedAt"] = now_iso()
        store.put_item(meta)
        sync_draft_summary(store, meta)
        write_audit(
            store,
            draft_id,
            actor or str(meta.get("owner") or ""),
            "generate",
            error=concise(message),
        )
    except Exception as exc:
        logger.error("failure_record_failed kind=%s", type(exc).__name__)
