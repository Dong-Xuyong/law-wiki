"""Lazy service locator.

Engine modules are imported inside methods so `app.api` imports cleanly while
those packages are still being written. Tests inject fakes on `Services`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.api.store import get_store


class Services:
    def __init__(
        self,
        store: Any = None,
        *,
        retriever_factory: Callable[[], Any] | None = None,
        llm_factory: Callable[[], Any] | None = None,
        draft_case: Callable[..., dict] | None = None,
        validate_packet: Callable[..., list] | None = None,
        render_docx: Callable[..., dict] | None = None,
        extract_pdf_bytes: Callable[..., dict] | None = None,
    ) -> None:
        self.store = store
        self.retriever_factory = retriever_factory
        self.llm_factory = llm_factory
        self.draft_case = draft_case
        self.validate_packet = validate_packet
        self.render_docx = render_docx
        self.extract_pdf_bytes = extract_pdf_bytes
        self._retriever: Any = None

    def repository(self) -> Any:
        if self.store is None:
            self.store = get_store()
        return self.store

    def retriever(self) -> Any:
        if self._retriever is not None:
            return self._retriever
        if self.retriever_factory is not None:
            self._retriever = self.retriever_factory()
            return self._retriever
        from app.engine.retrieve import Retriever
        from app.engine.retrieve.s3_index import ensure_local_index

        index_path = ensure_local_index()
        self._retriever = Retriever(index_path if isinstance(index_path, Path) else Path(index_path))
        return self._retriever

    def llm(self) -> Any:
        if self.llm_factory is not None:
            return self.llm_factory()
        from app.engine.draft.llm import BedrockLLM

        return BedrockLLM()

    def run_draft(self, record_text: str, **kwargs: Any) -> dict:
        function = self.draft_case
        if function is None:
            from app.engine.draft.pipeline import draft_case as function
        return function(record_text, **kwargs)

    def run_validate(self, packet: dict, *, catalog: dict) -> list:
        function = self.validate_packet
        if function is None:
            from app.engine.validate import validate_packet as function
        errors = function(packet, catalog=catalog)
        return list(errors or [])

    def run_render(self, packet: dict, *, template: Path, out_docx: Path, catalog: dict) -> dict:
        function = self.render_docx
        if function is None:
            from app.engine.render import render_docx as function
        return function(packet, template=template, out_docx=out_docx, catalog=catalog)

    def extract_pdf(self, data: bytes, filename: str) -> dict:
        function = self.extract_pdf_bytes
        if function is None:
            from app.engine.extract import extract_pdf_bytes as function
        return function(data, filename)


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services()
    return _services


def set_services(services: Services | None) -> None:
    global _services
    _services = services
