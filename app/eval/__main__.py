"""Evaluate stored packets offline, or draft cases live against the local index.

``python -m app.eval run --offline`` never calls Bedrock.
``python -m app.eval run --live`` is the only path that constructs ``BedrockLLM``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.eval.metrics import evaluate

INPUT_USD_PER_MILLION = Decimal("3")
OUTPUT_USD_PER_MILLION = Decimal("15")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_catalog(root: Path) -> dict[str, Any]:
    """Catalog mapping used to check source ids and paths."""
    try:
        from app.engine.render import load_local_catalog

        return load_local_catalog(root)
    except Exception:
        return _load_catalog_fallback(root)


def _load_catalog_fallback(root: Path) -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    data = root / "data"
    for name in ("catalog.jsonl", "open-sources-catalog.jsonl"):
        path = data / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            document_id = str(row.get("id") or "")
            if not document_id:
                continue
            rel_raw = row.get("rel_raw") or row.get("path") or ""
            rel_source = row.get("rel_source") or None
            catalog[document_id] = {
                "path": str(rel_raw).replace("\\", "/"),
                "title": str(row.get("title") or ""),
                "rel_source": str(rel_source).replace("\\", "/") if rel_source else None,
            }
    if not catalog:
        raise FileNotFoundError(f"No catalog JSONL under {data}")
    return catalog


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_files(root: Path, kind: str) -> list[Path]:
    base = root / "app" / "eval" / "cases" / kind
    return sorted(path for path in base.glob("*.json") if path.is_file())


def _read_raw_lines(root: Path, relative: str) -> list[str]:
    path = root / relative
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return text.splitlines()


def _slice_ranges(lines: list[str], ranges: list[list[int]]) -> str:
    chunks: list[str] = []
    for start, end in ranges:
        chunks.append("\n".join(lines[start - 1 : end]))
    return "\n".join(chunks)


def _record_text(root: Path, case: dict[str, Any], kind: str) -> str:
    if kind == "fictional":
        text = case.get("record_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{case.get('id')}: record_text is empty")
        return text
    lines = _read_raw_lines(root, str(case["path"]))
    ranges = case.get("input_line_ranges")
    if not isinstance(ranges, list) or not ranges:
        raise ValueError(f"{case.get('id')}: input_line_ranges is empty")
    return _slice_ranges(lines, ranges)


def _case_meta(case: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(case.get("title") or case.get("id") or "Minuta"),
        "process_number": "não indicado",
        "place": "Lisboa",
        "draft_date": datetime.now().date().isoformat(),
    }


def _usage_of(llm: Any) -> tuple[int, int]:
    usage = getattr(llm, "usage", None)
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("inputTokens") or 0), int(usage.get("outputTokens") or 0)


def estimate_cost(input_tokens: int, output_tokens: int) -> Decimal:
    cost = (
        Decimal(input_tokens) * INPUT_USD_PER_MILLION
        + Decimal(output_tokens) * OUTPUT_USD_PER_MILLION
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


def _summarize(case_id: str, kind: str, packet: dict[str, Any] | None, report: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    metrics = report or {}
    amounts = metrics.get("amounts") if isinstance(metrics, dict) else None
    return {
        "id": case_id,
        "kind": kind,
        "error": error,
        "decision_total": None if not isinstance(amounts, dict) else amounts.get("decision_total"),
        "expected_total": None if not isinstance(amounts, dict) else amounts.get("expected_total"),
        "exact_total": None if not isinstance(amounts, dict) else amounts.get("exact"),
        "metrics": metrics,
        "packet": packet,
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'id':<28} {'kind':<12} {'cite':>6} {'evid':>6} {'amt':>6} {'sec':>6} {'ment':>6} {'total':>10} {'valid':>6}")
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        def ratio(name: str) -> str:
            item = metrics.get(name)
            if not isinstance(item, dict) or item.get("ratio") is None:
                return "-"
            return f"{item['ratio']:.2f}"
        validation = metrics.get("validate_packet") if isinstance(metrics, dict) else None
        valid = "-"
        if isinstance(validation, dict):
            valid = str(validation.get("count")) if validation.get("available") else "n/a"
        total = row.get("decision_total") or "-"
        print(
            f"{str(row.get('id'))[:28]:<28} {str(row.get('kind'))[:12]:<12} "
            f"{ratio('citation_existence'):>6} {ratio('evidence_linkage'):>6} "
            f"{ratio('amounts'):>6} {ratio('section_completeness'):>6} "
            f"{ratio('must_mention'):>6} {str(total):>10} {valid:>6}"
        )
        if row.get("error"):
            print(f"  error: {row['error']}")


def _gate_failures(rows: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        citation = metrics.get("citation_existence") if isinstance(metrics, dict) else None
        ratio = citation.get("ratio") if isinstance(citation, dict) else None
        if ratio != 1.0:
            reasons.append(f"{row.get('id')}: citation_existence={ratio}")
        if row.get("kind") == "fictional" and row.get("exact_total") is not True:
            reasons.append(
                f"{row.get('id')}: decision_total {row.get('decision_total')!r} "
                f"!= expected {row.get('expected_total')!r}"
            )
    return reasons


def _write_report(root: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    out_dir = root / "build" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    json_path = out_dir / f"report-{stamp}.json"
    md_path = out_dir / f"report-{stamp}.md"
    stored = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    for case in stored.get("cases", []):
        case.pop("packet", None)
    json_path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Eval {payload.get('mode')} {payload.get('generated_at')}",
        "",
        "| id | kind | citation | evidence | amounts | sections | mentions | total | expected | validate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("cases", []):
        metrics = row.get("metrics") or {}
        def cell(name: str) -> str:
            item = metrics.get(name) or {}
            ratio = item.get("ratio")
            return "-" if ratio is None else f"{ratio:.2f}"
        validation = metrics.get("validate_packet") or {}
        valid = validation.get("count") if validation.get("available") else "n/a"
        lines.append(
            f"| {row.get('id')} | {row.get('kind')} | {cell('citation_existence')} | "
            f"{cell('evidence_linkage')} | {cell('amounts')} | {cell('section_completeness')} | "
            f"{cell('must_mention')} | {row.get('decision_total') or '-'} | "
            f"{row.get('expected_total') or '-'} | {valid} |"
        )
    if payload.get("cost_usd") is not None:
        lines.extend(["", f"Estimated Bedrock cost: USD {payload['cost_usd']}", ""])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_offline(root: Path, gate: bool) -> int:
    catalog = load_catalog(root)
    fixture_dir = root / "app" / "eval" / "fixtures" / "packets"
    paths = sorted(fixture_dir.glob("*.json"))
    if not paths:
        print(f"No packets in {fixture_dir}", file=sys.stderr)
        return 1
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            packet = _read_json(path)
            report = evaluate(packet, catalog, retriever=None, expected=None)
            rows.append(_summarize(path.stem, "fixture", packet, report, None))
        except Exception as exc:
            rows.append(_summarize(path.stem, "fixture", None, None, f"{type(exc).__name__}: {exc}"))
    _print_table(rows)
    return _finish(root, "offline", rows, gate, input_tokens=0, output_tokens=0, write=False)


def _construct_llm() -> Any:
    from app.engine.draft.llm import BedrockLLM
    import inspect

    signature = inspect.signature(BedrockLLM)
    required = [
        name
        for name, param in signature.parameters.items()
        if param.default is inspect.Parameter.empty
        and param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    if required:
        raise TypeError(
            "BedrockLLM requires arguments "
            + ", ".join(required)
            + "; refusing to guess them"
        )
    return BedrockLLM()


def run_live(root: Path, index: Path, kinds: list[str], limit: int | None, gate: bool) -> int:
    """Draft each selected case. Bedrock is imported only inside this function."""
    if not index.is_file():
        print(f"Index not found: {index}", file=sys.stderr)
        return 1
    from app.engine.draft.pipeline import draft_case
    from app.engine.retrieve import Retriever

    catalog = load_catalog(root)
    retriever = Retriever(index)
    llm = _construct_llm()
    selected: list[tuple[str, Path]] = []
    for kind in kinds:
        selected.extend((kind, path) for path in _case_files(root, kind))
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        print("No cases selected", file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    for kind, path in selected:
        case_id = path.stem
        try:
            case = _read_json(path)
            case_id = str(case.get("id") or case_id)
            record = _record_text(root, case, kind)
            expected = case.get("expected") if isinstance(case.get("expected"), dict) else None
            result = draft_case(
                record,
                llm=llm,
                retriever=retriever,
                case_meta=_case_meta(case),
            )
            packet = result.get("packet") if isinstance(result, dict) else None
            if not isinstance(packet, dict):
                raise ValueError("draft_case did not return a packet")
            report = evaluate(packet, catalog, retriever=retriever, expected=expected)
            rows.append(_summarize(case_id, kind, packet, report, None))
        except Exception as exc:
            rows.append(_summarize(case_id, kind, None, None, f"{type(exc).__name__}: {exc}"))

    input_tokens, output_tokens = _usage_of(llm)
    cost = estimate_cost(input_tokens, output_tokens)
    print(
        f"Estimated cost: USD {cost} "
        f"(input {input_tokens} tokens at USD 3/million, "
        f"output {output_tokens} tokens at USD 15/million)"
    )
    _print_table(rows)
    return _finish(
        root,
        "live",
        rows,
        gate,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        write=True,
    )


def _finish(
    root: Path,
    mode: str,
    rows: list[dict[str, Any]],
    gate: bool,
    *,
    input_tokens: int,
    output_tokens: int,
    write: bool,
) -> int:
    payload = {
        "mode": mode,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases": rows,
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
        "cost_usd": str(estimate_cost(input_tokens, output_tokens)) if mode == "live" else None,
    }
    if write:
        json_path, md_path = _write_report(root, payload)
        print(f"Wrote {json_path}")
        print(f"Wrote {md_path}")
    if not gate:
        return 0
    reasons = _gate_failures(rows)
    if reasons:
        print("Gate failed:", file=sys.stderr)
        for reason in reasons:
            print(f"- {reason}", file=sys.stderr)
        return 1
    print("Gate passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Score packets offline or draft cases live")
    run.add_argument("--offline", action="store_true", help="Score fixtures; do not call Bedrock")
    run.add_argument("--live", action="store_true", help="Call BedrockLLM via draft_case")
    run.add_argument("--index", help="FTS index path, required with --live")
    run.add_argument("--cases", choices=("fictional", "backtest", "all"))
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--gate", action="store_true")
    run.add_argument("--root", default=None, help="Repository root (defaults to this repo)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.error("unknown command")
    if args.offline == args.live:
        parser.error("pass exactly one of --offline or --live")
    root = Path(args.root).resolve() if args.root else repo_root()
    if args.offline:
        if args.index or args.cases or args.limit is not None:
            print("--index, --cases and --limit apply to --live only", file=sys.stderr)
        return run_offline(root, args.gate)
    if not args.index or not args.cases:
        parser.error("--live requires --index and --cases")
    kinds = ["fictional", "backtest"] if args.cases == "all" else [args.cases]
    index = Path(args.index)
    if not index.is_absolute():
        index = root / index
    return run_live(root, index, kinds, args.limit, args.gate)


if __name__ == "__main__":
    sys.exit(main())
