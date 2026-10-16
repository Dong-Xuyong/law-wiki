# Minutas app contracts

Single source of truth for the interfaces between components. Change it only
through the supervisor. Python 3.12 compatible (Lambda runtime); run locally with
`C:\Users\Dong\miniconda3\python.exe` from the repository root.

## Hard rules

- No real case data. Only fictional cases and published decisions until the CSM
  validates the tool (CSM recommendation 8, 8 April 2026). The UI shows a banner,
  and creating a case requires `fictional: true`.
- Legal authorities come only from the local corpus (`raw/documents/**`) listed in
  `data/catalog.jsonl` and `data/open-sources-catalog.jsonl`. Never from model memory.
- Strict evidence: a fact is proved only with basis `common`, `admission`, or
  `procedural_record` (see `.cursor/skills/law-wiki/reference.md`).
- Drafts are never final until every paragraph is reviewed. DOCX export appends:
  `Decisão produzida com o auxílio de sistema de IA, de acordo com as recomendações do CSM. Integralmente revisto pelo signatário.`
- Every rendered page keeps the template marker
  `MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA`.
- Cost: lean mode. No WAF, no S3 Vectors in v1, budget alarm 10 USD/month.
  Bedrock is called only when a user generates a draft (or an explicit `--live` eval).
- Region `eu-west-1`. Bedrock only through `eu.` inference profiles.

## Layout and ownership

| Path | Owner |
|---|---|
| `app/CONTRACTS.md`, `app/__init__.py` and package `__init__.py` stubs | supervisor |
| `app/infra/` | agent 1 (infra) |
| `app/engine/extract.py`, `render.py`, `validate.py`, `app/engine/templates/`, `app/tests/test_engine_*.py` | agent 2 (engine core) |
| `app/engine/draft/`, `app/tests/test_draft_*.py` | agent 3 (drafting) |
| `app/engine/retrieve/`, `app/ingest/index_fts.py`, `app/tests/test_retrieve_*.py` | agent 4 (retrieval) |
| `app/ingest/sources/`, new `raw/documents/opensrc/**`, new `wiki/sources/*--law_*.md` for them, `data/open-sources-catalog.jsonl`, the merge in `scripts/build_web_catalog.py`, `app/tests/test_opensrc_*.py` | agent 5 (corpus) |
| `data/enrichment/**`, `data/connections.jsonl`, graph scripts in `scripts/` (`select_pilot.py`, `extract_legal_signals.py`, `build_connection_graph.py`, `lint_wiki.py`, new `scripts/graph_tranche.py`) | agent 6 (graph) |
| `app/api/`, `app/tests/test_api_*.py` | agent 7 (API) |
| `app/web/` | agent 8 (web) |
| `app/eval/`, `app/tests/test_eval_*.py` | agent 9 (eval) |
| `docs/app/` | agent 10 (docs) |

Never edit another owner's files. Never run git. App tests live in `app/tests/`
(not `tests/`, which the public Pages CI runs without these dependencies).
Run them with `python -m unittest discover -s app/tests -t .`.

Python dependencies for Lambda: `app/requirements.txt` (supervisor-owned):
`python-docx>=1.1,<2`, `pypdf>=6.0,<7`. `boto3` is provided by the Lambda runtime.

## Catalog

`catalog: dict[str, dict]` maps `document_id` to
`{"path": "raw/documents/.../law_x.md", "title": str, "rel_source": str | None}`.
Locally it is built from both catalog JSONL files. In Lambda it comes from the
index (`Retriever.catalog()`), because raw files are not present there.

Line pinpoints are 1-based line numbers of the raw file after normalising line
endings to `\n`.

## Engine core (agent 2): `app.engine`

```python
from app.engine.extract import extract_pdf_bytes   # (data: bytes, filename: str) -> {"text": str, "manifest": dict}
from app.engine.validate import validate_packet    # (packet: dict, *, catalog: dict) -> list[str]   (errors; [] means valid)
from app.engine.render import render_docx          # (packet: dict, *, template: Path, out_docx: Path, catalog: dict) -> dict  (source manifest)
from app.engine.render import load_local_catalog   # (root: Path) -> dict
```

- Same packet schema and rules as `.cursor/skills/law-wiki/reference.md`.
- Must not require raw files on disk when `catalog` is given; validate
  `document_id`/`path` pairs against `catalog`.
- Must ignore extra paragraph keys `id`, `confidence`, `note`.
- PDF export is optional and Windows-only; never imported in Lambda.
- Template copied to `app/engine/templates/decisao-arbitral-wiki.docx`.

## Retrieval (agent 4): `app.engine.retrieve`

```python
from app.engine.retrieve import Retriever
r = Retriever(index_path: Path)
r.search(query: str, k: int = 8, filters: dict | None = None) -> list[Passage]
r.lines(document_id: str, line_start: int, line_end: int) -> str
r.verify_quote(document_id: str, line_start: int, line_end: int, quote: str) -> bool
r.catalog() -> dict   # catalog shape above
```

`Passage = {"document_id", "path", "title", "line_start", "line_end", "text", "score"}`.
`filters` may contain `website`, `year`, `kind` (`arbitral` | `legislation` | `case_law`).
Index file built by `python -m app.ingest.index_fts --root . --out build/index/fts.sqlite3`
(SQLite FTS5, Portuguese-friendly tokenizer `unicode61 remove_diacritics 2`).
Covers every document in both catalogs. Verification normalises whitespace and
diacritics-insensitive matching is NOT allowed for quotes (exact text after
whitespace normalisation).

## Drafting (agent 3): `app.engine.draft`

```python
from app.engine.draft.llm import BedrockLLM, LLM   # LLM protocol
llm.complete_json(system: str, user: str, schema: dict, *, max_tokens: int = 8000) -> dict
llm.model_id: str; llm.usage: {"inputTokens": int, "outputTokens": int}   # cumulative

from app.engine.draft.pipeline import draft_case
draft_case(record_text: str, *, llm: LLM, retriever: Retriever, case_meta: dict,
           input_record: dict | None = None, max_repairs: int = 2) -> DraftResult
```

`DraftResult = {"packet": dict, "paragraphs": [Paragraph], "errors": [str], "audit": {"modelId", "promptSha256", "inputTokens", "outputTokens", "sourceIds": [str]}}`.
`errors == []` only when `validate_packet` passes. `case_meta` keys: `title`,
`process_number` (default `"não indicado"`), `place`, `draft_date` (YYYY-MM-DD).
Default model id env `LW_MODEL_ID`, default value
`eu.anthropic.claude-sonnet-4-5-20250929-v1:0`. A `FakeLLM` lives in
`app/engine/draft/fakes.py` for tests.

`Paragraph = {"id": "<section>-<index>", "section", "index", "text", "sourceIds": [str], "evidenceIds": [str], "confidence": "high"|"medium"|"low", "note": str}`
(index is 0-based within the section, in packet order).

## API (agent 7): `app.api`

Two Lambda handlers (Python 3.12, HTTP API payload v2, JWT claims at
`event.requestContext.authorizer.jwt.claims`, owner = claim `sub`):

- `app.api.handler.handle`: REST router.
- `app.api.worker.handle`: draft worker invoked by Step Functions with `{"caseId", "draftId"}`.

All routes are under `/api`, JSON bodies, errors `{"error": code, "message": str}`:

| Method and path | Body | Response |
|---|---|---|
| GET `/api/me` | | `{"sub", "email"}` |
| GET `/api/cases` | | `{"items": [Case]}` |
| POST `/api/cases` | `{"title", "text"?, "inputKind": "text"\|"pdf", "fictional": true}` | 201 `{"case": Case, "uploadUrl"?: str}` (PUT URL, 10 min, PDF only, max 15 MB) |
| GET `/api/cases/{caseId}` | | `{"case": Case, "drafts": [DraftSummary]}` |
| POST `/api/cases/{caseId}/drafts` | | 202 `{"draftId", "status": "queued"}` |
| GET `/api/drafts/{draftId}` | | `Draft` |
| PATCH `/api/drafts/{draftId}/paragraphs/{paragraphId}` | `{"action": "accept"\|"edit"\|"reject", "text"?}` | `ReviewParagraph` |
| POST `/api/drafts/{draftId}/export` | | `{"url"}` presigned GET 10 min; 409 `{"error": "unreviewed", "remaining": n}` or `{"error": "section_empty", "section"}` |
| GET `/api/search?q=&k=` | | `{"items": [Passage]}` |
| GET `/api/sources/{documentId}/lines?start=&end=` | | `{"documentId", "title", "path", "lineStart", "lineEnd", "text", "publicUrl"}` (max 200 lines; `publicUrl` = `https://dong-xuyong.github.io/law-wiki/documents/{documentId}/`) |

`fictional` must be `true` or the API returns 400 `fictional_required`.

- `Case = {"caseId", "title", "inputKind", "status": "new"|"ready", "createdAt", "updatedAt"}`
- `DraftSummary = {"draftId", "status", "createdAt"}`
- `Draft = {"draftId", "caseId", "status": "queued"|"running"|"ready"|"failed", "error"?, "modelId", "createdAt", "evidence": [...packet.evidence_matrix], "sources": [...packet.sources], "amounts": [...], "decisionTotal", "paragraphs": [ReviewParagraph], "reviewedCount", "totalCount"}`
- `ReviewParagraph = Paragraph + {"originalText", "review": {"status": "pending"|"accepted"|"edited"|"rejected", "by", "at"}}`

Export builds the packet from reviewed paragraphs (edited text replaces, rejected
removed, every required section must stay non-empty), appends the CSM sentence
to `decisao`, renders with `render_docx`, stores `exports/{draftId}.docx`.

### DynamoDB (single table, env `LW_TABLE`, keys `PK`, `SK`, on-demand)

| Item | PK | SK | Notes |
|---|---|---|---|
| Case | `USER#{sub}` | `CASE#{caseId}` | Case fields, `inputKey` |
| Draft summary | `CASE#{caseId}` | `DRAFT#{draftId}` | `status`, `createdAt` |
| Draft meta | `DRAFT#{draftId}` | `META` | `caseId`, `owner`, `status`, `error`, `modelId`, `packetKey`, counts |
| Paragraph | `DRAFT#{draftId}` | `PARA#{paragraphId}` | ReviewParagraph fields |
| Audit | `AUDIT#{draftId}` | `{iso8601}#{rand4}` | `actor`, `action` (`generate`\|`accept`\|`edit`\|`reject`\|`export`), `paragraphId`?, `modelId`?, `promptSha256`?, `sourceIds`?, `textSha256`? |

Ids: `caseId` = `c_` + 10 chars `[a-z0-9]`; `draftId` = `d_` + 10 chars.
Every request checks the item owner equals the caller `sub` (404 otherwise).

### S3 (env `LW_CASES_BUCKET`, SSE-KMS)

`cases/{caseId}/input.pdf`, `cases/{caseId}/input.txt`, `drafts/{draftId}/packet.json`, `exports/{draftId}.docx`.

## Environment variables (set by infra on both Lambdas)

`LW_TABLE`, `LW_CASES_BUCKET`, `LW_CORPUS_BUCKET`, `LW_INDEX_S3_KEY` (default
`index/fts.sqlite3`; downloaded to `/tmp/fts.sqlite3` on cold start),
`LW_TEMPLATE_PATH` (default bundled `app/engine/templates/decisao-arbitral-wiki.docx`),
`LW_MODEL_ID`, `LW_REGION` (`eu-west-1`), `LW_STATE_MACHINE_ARN` (API only).

## Infra (agent 1)

- Lambda code: asset folder `build/lambda/` produced by
  `python app/infra/scripts/build_lambda.py` (pip install `app/requirements.txt`
  for `manylinux2014_x86_64`, Python 3.12, plus the `app/` package without
  `web/`, `infra/`, `tests/`, `eval/`). Runtime Python 3.12, x86_64.
  `api`: 1024 MB, 30 s, ephemeral 3072 MB. `draft_worker`: 1024 MB, 900 s, ephemeral 3072 MB.
- Web: `app/web/dist/` deployed to the web bucket, plus `config.json`
  `{"apiBase": "/api", "region", "userPoolId", "clientId", "cognitoDomain", "redirectUri"}`.
- CloudFront: default behaviour to the web bucket (OAC, SPA fallback to
  `index.html`), `/api/*` behaviour to the HTTP API (no caching, all methods,
  forwards `Authorization`). No WAF.
- Cognito: self sign-up off, MFA required (TOTP), managed login domain,
  public app client with authorization code + PKCE, callback URLs
  `https://<cloudfront>/` and `http://localhost:5173/`.
- Budget alarm 10 USD/month to `xuyongdong0@gmail.com`.

## Web (agent 8)

Reads `/config.json` at start (local dev: `app/web/public/config.json` with
`apiBase` pointing at a mock or deployed API). pt-PT UI.
