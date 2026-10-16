"""Command line for one explicit draft.

Without ``--live`` the process refuses to call Amazon Bedrock.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence


REFUSAL = (
    "Sem --live, a minuta não é gerada: este comando recusa-se a chamar o Amazon Bedrock. "
    "Repita com --live apenas para uma geração explícita."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.engine.draft.cli",
        description="Gera um pacote de minuta a partir de um registo textual.",
    )
    parser.add_argument("--record", required=True, help="Ficheiro de texto do registo.")
    parser.add_argument("--index", required=True, help="Índice SQLite FTS do corpus.")
    parser.add_argument("--out", required=True, help="Destino do packet JSON.")
    parser.add_argument("--title", default=None, help="Título curto da minuta.")
    parser.add_argument("--place", default=None, help="Lugar da minuta.")
    parser.add_argument("--draft-date", default=None, help="Data ISO da minuta.")
    parser.add_argument(
        "--process-number",
        default=None,
        help="Número do processo, se o caso o indicar.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Autoriza uma chamada real ao Bedrock.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.live:
        print(REFUSAL)
        return 2
    return _run_live(args)


def _run_live(args: argparse.Namespace) -> int:
    import json
    from datetime import date
    from pathlib import Path

    from app.engine.draft.llm import BedrockLLM
    from app.engine.draft.pipeline import draft_case

    try:
        from app.engine.retrieve import Retriever
    except ImportError as exc:
        print(f"Retriever indisponível: {exc}", file=sys.stderr)
        return 1

    record_path = Path(args.record)
    if not record_path.is_file():
        print(f"Registo não encontrado: {record_path}", file=sys.stderr)
        return 1
    text = record_path.read_text(encoding="utf-8")
    case_meta = {
        "title": args.title or record_path.stem,
        "place": args.place or "Local não indicado",
        "draft_date": args.draft_date or date.today().isoformat(),
    }
    if args.process_number:
        case_meta["process_number"] = args.process_number
    result = draft_case(
        text,
        llm=BedrockLLM(),
        retriever=Retriever(Path(args.index)),
        case_meta=case_meta,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result["packet"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    audit = result["audit"]
    print(
        f"model={audit['modelId']} errors={len(result['errors'])} "
        f"paragraphs={len(result['paragraphs'])}"
    )
    for error in result["errors"]:
        print(error, file=sys.stderr)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
