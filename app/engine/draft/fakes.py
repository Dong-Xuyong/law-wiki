"""Offline stand-ins for the drafting model and the corpus retriever."""

from __future__ import annotations

import copy
import re
from typing import Any, Callable


_STEP_RE = re.compile(r"(?m)^PASSO:\s*([A-Za-z0-9_-]+)\s*$")
_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÿ]{3,}")
_QUERY_STOP = {
    "para",
    "com",
    "uma",
    "por",
    "dos",
    "das",
    "que",
    "nao",
    "não",
    "nos",
    "num",
    "pelo",
    "pela",
}


def normalize_ws(text: str) -> str:
    """Collapse whitespace. Diacritics and case stay untouched."""

    return re.sub(r"\s+", " ", str(text).replace("\u00a0", " ")).strip()


def _step_name(user: str) -> str:
    match = _STEP_RE.search(user or "")
    return match.group(1) if match else ""


def _query_tokens(query: str) -> list[str]:
    tokens = []
    for token in _TOKEN_RE.findall(query.casefold()):
        if token in _QUERY_STOP:
            continue
        tokens.append(token)
    return tokens


class FakeLLM:
    """Scripted ``complete_json`` for tests.

    ``responses`` is either a list consumed in call order or a mapping from
    the ``PASSO:`` name in the user prompt to a dict, a list of dicts, or a
    callable ``(system, user, schema) -> dict``. Each successful call adds
    ``input_tokens`` and ``output_tokens`` to the cumulative ``usage``.
    """

    def __init__(
        self,
        responses: dict[str, Any] | list[Any] | None = None,
        *,
        model_id: str = "fake-model",
        input_tokens: int = 100,
        output_tokens: int = 40,
    ) -> None:
        self.model_id = model_id
        self.usage = {"inputTokens": 0, "outputTokens": 0}
        self.calls: list[dict[str, Any]] = []
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        if isinstance(responses, list):
            self._queue = list(responses)
            self._by_step: dict[str, Any] = {}
        else:
            self._queue = []
            self._by_step = dict(responses or {})

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = 8000,
    ) -> dict[str, Any]:
        step = _step_name(user)
        self.calls.append(
            {
                "step": step,
                "system": system,
                "user": user,
                "schema": schema,
                "max_tokens": max_tokens,
            }
        )
        payload = self._next_payload(step)
        if callable(payload):
            result = payload(system, user, schema)
        else:
            result = copy.deepcopy(payload)
        if not isinstance(result, dict):
            raise TypeError("FakeLLM responses must be JSON objects.")
        self.usage["inputTokens"] += self._input_tokens
        self.usage["outputTokens"] += self._output_tokens
        return result

    def _next_payload(self, step: str) -> Any:
        if step and step in self._by_step:
            script = self._by_step[step]
            if isinstance(script, list):
                if not script:
                    return {}
                return script.pop(0)
            return script
        if self._queue:
            return self._queue.pop(0)
        return {}


class FakeRetriever:
    """In-memory retriever with the ``Retriever`` method names.

    ``documents`` are dicts with ``document_id``, ``path``, ``title`` and
    ``text`` (full file, ``\\n`` line breaks). Optional ``rel_source``,
    ``website``, ``year`` and ``kind`` are stored for ``catalog`` and filters.
    Quote checks compare exact text after whitespace normalisation.
    """

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = [dict(document) for document in (documents or [])]
        self.searches: list[dict[str, Any]] = []

    def catalog(self) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}
        for document in self.documents:
            document_id = document.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                continue
            catalog[document_id] = {
                "path": document.get("path") or "",
                "title": document.get("title") or document_id,
                "rel_source": document.get("rel_source"),
            }
        return catalog

    def search(
        self,
        query: str,
        k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.searches.append({"query": query, "k": k, "filters": filters})
        tokens = _query_tokens(query)
        hits: list[dict[str, Any]] = []
        if not tokens:
            return hits
        for document in self.documents:
            if not _allows(document, filters):
                continue
            passage = self._passage(document, tokens)
            if passage is not None:
                hits.append(passage)
        hits.sort(key=lambda item: (-item["score"], item["document_id"]))
        return hits[: max(0, int(k))]

    def lines(self, document_id: str, line_start: int, line_end: int) -> str:
        rows = self._rows(document_id)
        if not rows:
            return ""
        start = max(1, int(line_start))
        end = min(len(rows), int(line_end))
        if end < start:
            return ""
        return "\n".join(rows[start - 1 : end])

    def verify_quote(
        self,
        document_id: str,
        line_start: int,
        line_end: int,
        quote: str,
    ) -> bool:
        excerpt = normalize_ws(self.lines(document_id, line_start, line_end))
        needle = normalize_ws(quote)
        if not needle or not excerpt:
            return False
        return needle in excerpt

    def _rows(self, document_id: str) -> list[str]:
        for document in self.documents:
            if document.get("document_id") == document_id:
                return str(document.get("text") or "").split("\n")
        return []

    def _passage(
        self,
        document: dict[str, Any],
        tokens: list[str],
    ) -> dict[str, Any] | None:
        text = str(document.get("text") or "")
        haystack = text.casefold()
        score = sum(1 for token in tokens if token in haystack)
        if score <= 0:
            return None
        rows = text.split("\n")
        if not rows:
            return None
        if len(rows) <= 40:
            start, end = 1, len(rows)
        else:
            best_line = 1
            best_score = -1
            for number, line in enumerate(rows, start=1):
                folded = line.casefold()
                line_score = sum(1 for token in tokens if token in folded)
                if line_score > best_score:
                    best_score = line_score
                    best_line = number
            start = max(1, best_line - 5)
            end = min(len(rows), best_line + 15)
        return {
            "document_id": document.get("document_id"),
            "path": document.get("path") or "",
            "title": document.get("title") or "",
            "line_start": start,
            "line_end": end,
            "text": "\n".join(rows[start - 1 : end]),
            "score": float(score),
        }


def _allows(document: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    for key in ("website", "year", "kind"):
        if key not in filters or filters[key] is None:
            continue
        if document.get(key) != filters[key]:
            return False
    return True


Script = dict[str, Any] | Callable[..., dict[str, Any]]
