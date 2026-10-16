"""Read-only FTS5 retriever. One connection per instance."""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from .query import build_match_query, phrase_bonus

_WS_RE = re.compile(r"\s+")
_FILTER_COLUMNS = ("website", "year", "kind")


class Retriever:
    """Search the local corpus index and verify quotes against exact lines.

    ``search`` scores are higher-is-better: negated FTS5 ``bm25`` plus a bonus
    when the passage contains a citation phrase from the query (``261/2004``,
    ``artigo 7``). Windows overlap by design, so neighbouring hits can share a
    document. ``verify_quote`` compares whitespace-collapsed text only: case and
    diacritics must match.
    """

    def __init__(self, index_path: Path) -> None:
        path = Path(index_path)
        if not path.is_file():
            raise FileNotFoundError(f"FTS index not found: {path}")
        uri = path.resolve().as_uri() + "?mode=ro"
        self._conn = sqlite3.connect(
            uri,
            uri=True,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA query_only=ON")
        self._lock = threading.Lock()
        self.index_path = path

    def close(self) -> None:
        with self._lock:
            conn = self._conn
            self._conn = None
            if conn is not None:
                conn.close()

    def __enter__(self) -> "Retriever":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(
        self,
        query: str,
        k: int = 8,
        filters: dict | None = None,
    ) -> list[dict]:
        k = int(k)
        if k <= 0:
            return []
        if filters is not None and not isinstance(filters, dict):
            raise TypeError("filters must be a dict or None")
        prepared = build_match_query(query or "")
        if not prepared.match:
            return []

        where = ["passages MATCH ?"]
        params: list = [prepared.match]
        for column, value in _filter_pairs(filters):
            where.append(f"docs.{column} = ?")
            params.append(value)
        pool = min(max(k * 15, 50), 500)
        params.append(pool)
        sql = (
            "SELECT docs.document_id AS document_id, docs.path AS path, "
            "docs.title AS title, passages.line_start AS line_start, "
            "passages.line_end AS line_end, passages.\"text\" AS passage_text, "
            "bm25(passages) AS bm "
            "FROM passages "
            "JOIN docs ON docs.document_id = passages.document_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY bm25(passages) "
            "LIMIT ?"
        )
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(sql, params).fetchall()

        hits: list[dict] = []
        for row in rows:
            text = row["passage_text"] or ""
            bm = row["bm"]
            base = 0.0 if bm is None else -float(bm)
            hits.append(
                {
                    "document_id": row["document_id"],
                    "path": row["path"] or "",
                    "title": row["title"] or "",
                    "line_start": int(row["line_start"]),
                    "line_end": int(row["line_end"]),
                    "text": text,
                    "score": base + phrase_bonus(text, prepared),
                }
            )
        hits.sort(
            key=lambda hit: (
                -hit["score"],
                hit["document_id"],
                hit["line_start"],
                hit["line_end"],
            )
        )
        return hits[:k]

    def lines(self, document_id: str, line_start: int, line_end: int) -> str:
        start = int(line_start)
        end = int(line_end)
        if end < start:
            return ""
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                "SELECT text FROM lines "
                "WHERE document_id = ? AND line_no >= ? AND line_no <= ? "
                "ORDER BY line_no",
                (document_id, start, end),
            ).fetchall()
        return "\n".join(row["text"] for row in rows)

    def verify_quote(
        self,
        document_id: str,
        line_start: int,
        line_end: int,
        quote: str,
    ) -> bool:
        haystack = _collapse_whitespace(
            self.lines(document_id, line_start, line_end)
        )
        needle = _collapse_whitespace(quote)
        return needle in haystack

    def catalog(self) -> dict[str, dict[str, str | None]]:
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                "SELECT document_id, path, title, rel_source FROM docs"
            ).fetchall()
        return {
            row["document_id"]: {
                "path": row["path"],
                "title": row["title"],
                "rel_source": row["rel_source"],
            }
            for row in rows
        }

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Retriever is closed")
        return self._conn


def _filter_pairs(filters: dict | None) -> list[tuple[str, str]]:
    if not filters:
        return []
    pairs: list[tuple[str, str]] = []
    for column in _FILTER_COLUMNS:
        if column not in filters or filters[column] is None:
            continue
        pairs.append((column, str(filters[column])))
    return pairs


def _collapse_whitespace(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()
