"""Build the SQLite FTS5 index used by ``app.engine.retrieve``.

    python -m app.ingest.index_fts --root . --out build/index/fts.sqlite3

Reads ``data/catalog.jsonl`` (kind ``arbitral``) and, when present,
``data/open-sources-catalog.jsonl`` (kind taken from the row). Line numbers are
1-based over the raw file after newline normalisation. Passage windows skip a
leading YAML frontmatter block but keep those file line numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

WINDOW_LINES = 12
WINDOW_OVERLAP = 4
_COMMIT_EVERY = 200
_KNOWN_KINDS = frozenset({"arbitral", "legislation", "case_law"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the SQLite FTS5 index for Minutas retrieval."
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        stats = build_index(args.root, args.out, verbose=True)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for row in stats["skipped_rows"]:
        print(f"SKIP {row['reason']} id={row['id']} path={row['path']}")
    print(format_summary(stats), flush=True)
    return 0


def format_summary(stats: dict) -> str:
    size_mb = stats["size_bytes"] / (1024 * 1024)
    kinds = ",".join(
        f"{name}:{count}" for name, count in sorted(stats["kinds"].items())
    )
    return (
        f"docs={stats['docs']} passages={stats['passages']} lines={stats['lines']} "
        f"skipped={stats['skipped']} size_mb={size_mb:.3f} "
        f"duration_s={stats['seconds']:.2f} kinds={kinds}"
    )


def build_index(root: Path, out: Path, *, verbose: bool = False) -> dict:
    """Build ``out`` via a temp file in the same directory, then replace it."""

    started = time.perf_counter()
    root = Path(root).resolve()
    out = Path(out)
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    primary = root / "data" / "catalog.jsonl"
    if not primary.is_file():
        raise FileNotFoundError(f"missing catalog: {primary}")

    jobs, skipped = _load_jobs(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    _remove_sidecars(tmp)

    conn = sqlite3.connect(tmp, isolation_level=None)
    try:
        _create_schema(conn)
        counts = _fill(conn, jobs, skipped, verbose=verbose)
        conn.execute("INSERT INTO passages(passages) VALUES('optimize')")
    except Exception:
        conn.close()
        if tmp.exists():
            tmp.unlink()
        _remove_sidecars(tmp)
        raise
    conn.close()

    try:
        _remove_sidecars(out)
        os.replace(tmp, out)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    seconds = time.perf_counter() - started
    return {
        "docs": counts["docs"],
        "passages": counts["passages"],
        "lines": counts["lines"],
        "skipped": len(skipped),
        "skipped_rows": skipped,
        "kinds": counts["kinds"],
        "size_bytes": out.stat().st_size,
        "seconds": seconds,
    }


def normalize_lines(text: str) -> list[str]:
    """Split on ``\\n`` after converting CR LF and CR. A final newline is not a line."""

    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def body_start_line(lines: list[str]) -> int:
    """1-based first line after a leading ``---`` YAML block, else 1."""

    if not lines or lines[0].strip() != "---":
        return 1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index + 2
    return 1


def passage_spans(
    body_start: int,
    n_lines: int,
    window: int = WINDOW_LINES,
    overlap: int = WINDOW_OVERLAP,
) -> list[tuple[int, int]]:
    """Inclusive 1-based windows of ``window`` lines stepping by ``window - overlap``."""

    if n_lines <= 0 or body_start > n_lines:
        return []
    if window < 1:
        raise ValueError("window must be >= 1")
    stride = max(window - overlap, 1)
    body_len = n_lines - body_start + 1
    spans: list[tuple[int, int]] = []
    offset = 0
    while offset < body_len:
        length = min(window, body_len - offset)
        start = body_start + offset
        spans.append((start, start + length - 1))
        if offset + window >= body_len:
            break
        offset += stride
    return spans


def _load_jobs(root: Path) -> tuple[list[dict], list[dict]]:
    primary = root / "data" / "catalog.jsonl"
    secondary = root / "data" / "open-sources-catalog.jsonl"
    sources: list[tuple[Path, bool]] = [(primary, True)]
    if secondary.is_file():
        sources.append((secondary, False))

    jobs: list[dict] = []
    skipped: list[dict] = []
    accepted: set[str] = set()
    for src, force_arbitral in sources:
        with src.open(encoding="utf-8-sig") as handle:
            for line_no, raw_line in enumerate(handle, 1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError:
                    skipped.append(
                        {
                            "id": "",
                            "path": "",
                            "reason": f"invalid json {src.name}:{line_no}",
                        }
                    )
                    continue
                if not isinstance(row, dict):
                    skipped.append(
                        {
                            "id": "",
                            "path": "",
                            "reason": f"invalid json {src.name}:{line_no}",
                        }
                    )
                    continue
                job, skip = _job_from_row(root, row, force_arbitral, accepted)
                if skip is not None:
                    skipped.append(skip)
                    continue
                assert job is not None
                accepted.add(job["document_id"])
                jobs.append(job)
    return jobs, skipped


def _job_from_row(
    root: Path,
    row: dict,
    force_arbitral: bool,
    accepted: set[str],
) -> tuple[dict | None, dict | None]:
    doc_id_raw = row.get("id")
    rel_raw_value = row.get("rel_raw")
    if doc_id_raw is None or rel_raw_value is None:
        return None, {"id": "", "path": "", "reason": "missing id or rel_raw"}
    doc_id = str(doc_id_raw).strip()
    rel_raw = str(rel_raw_value).strip().replace("\\", "/")
    if not doc_id or not rel_raw:
        return None, {
            "id": doc_id,
            "path": rel_raw,
            "reason": "missing id or rel_raw",
        }
    if doc_id in accepted:
        return None, {"id": doc_id, "path": rel_raw, "reason": "duplicate id"}

    full = (root / rel_raw).resolve()
    if not full.is_relative_to(root):
        return None, {"id": doc_id, "path": rel_raw, "reason": "path outside root"}
    if not full.is_file():
        return None, {"id": doc_id, "path": rel_raw, "reason": "missing file"}

    if force_arbitral:
        kind = "arbitral"
    else:
        raw_kind = row.get("kind")
        kind = str(raw_kind).strip() if raw_kind is not None else ""
        if kind.lower() in _KNOWN_KINDS:
            kind = kind.lower()

    title_raw = row.get("title")
    title = str(title_raw).strip() if title_raw is not None else ""
    rel_source_raw = row.get("rel_source")
    if rel_source_raw is None:
        rel_source = None
    else:
        rel_source = str(rel_source_raw).strip() or None

    return (
        {
            "document_id": doc_id,
            "path": rel_raw,
            "full": full,
            "title": title,
            "website": _optional_text(row.get("website")),
            "year": _year_text(row.get("year")),
            "kind": kind,
            "rel_source": rel_source,
        },
        None,
    )


def _fill(
    conn: sqlite3.Connection,
    jobs: list[dict],
    skipped: list[dict],
    *,
    verbose: bool,
) -> dict:
    docs = 0
    passages = 0
    lines = 0
    kinds: dict[str, int] = {}
    conn.execute("BEGIN")
    try:
        for index, job in enumerate(jobs, 1):
            try:
                text = job["full"].read_text(encoding="utf-8-sig")
            except (UnicodeDecodeError, OSError) as exc:
                skipped.append(
                    {
                        "id": job["document_id"],
                        "path": job["path"],
                        "reason": f"unreadable file ({exc.__class__.__name__})",
                    }
                )
                continue
            file_lines = normalize_lines(text)
            spans = passage_spans(body_start_line(file_lines), len(file_lines))
            conn.execute(
                "INSERT INTO docs("
                "document_id, path, title, website, year, kind, rel_source, line_count"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job["document_id"],
                    job["path"],
                    job["title"],
                    job["website"],
                    job["year"],
                    job["kind"],
                    job["rel_source"],
                    len(file_lines),
                ),
            )
            conn.executemany(
                "INSERT INTO lines(document_id, line_no, text) VALUES (?, ?, ?)",
                (
                    (job["document_id"], line_no, line_text)
                    for line_no, line_text in enumerate(file_lines, 1)
                ),
            )
            conn.executemany(
                "INSERT INTO passages(text, document_id, line_start, line_end) "
                "VALUES (?, ?, ?, ?)",
                (
                    (
                        "\n".join(file_lines[start - 1 : end]),
                        job["document_id"],
                        start,
                        end,
                    )
                    for start, end in spans
                ),
            )
            docs += 1
            lines += len(file_lines)
            passages += len(spans)
            kinds[job["kind"]] = kinds.get(job["kind"], 0) + 1
            if index % _COMMIT_EVERY == 0:
                conn.commit()
                conn.execute("BEGIN")
                if verbose and docs % 1000 == 0:
                    print(f"indexed {docs} docs...", flush=True)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    if verbose and docs:
        print(f"indexed {docs} docs...", flush=True)
    return {"docs": docs, "passages": passages, "lines": lines, "kinds": kinds}


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA page_size=8192")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-65536")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute("PRAGMA user_version=1")
    conn.execute(
        """
        CREATE TABLE docs (
            document_id TEXT PRIMARY KEY NOT NULL,
            path TEXT NOT NULL,
            title TEXT NOT NULL,
            website TEXT,
            year TEXT,
            kind TEXT NOT NULL,
            rel_source TEXT,
            line_count INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE lines (
            document_id TEXT NOT NULL,
            line_no INTEGER NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (document_id, line_no)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE passages USING fts5(
            text,
            document_id UNINDEXED,
            line_start UNINDEXED,
            line_end UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        )
        """
    )
    conn.execute("CREATE INDEX idx_docs_kind ON docs(kind)")
    conn.execute("CREATE INDEX idx_docs_website ON docs(website)")
    conn.execute("CREATE INDEX idx_docs_year ON docs(year)")
    conn.execute(
        """
        CREATE TABLE index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO index_meta(key, value) VALUES (?, ?)",
        (
            ("tokenizer", "unicode61 remove_diacritics 2"),
            ("window", str(WINDOW_LINES)),
            ("overlap", str(WINDOW_OVERLAP)),
        ),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _year_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()


if __name__ == "__main__":
    sys.exit(main())
