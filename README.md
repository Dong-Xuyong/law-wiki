# Law Wiki

Obsidian vault for legal research. Immutable documents live in `raw/`. Linked digests, topics, and organizations live in `wiki/`. The LLM maintains the wiki; you curate sources and questions.

This is a **research aid**, not legal advice.

## Quick start (Obsidian)

1. In Obsidian: **Open folder as vault** → `C:\Users\Dong\Desktop\Knowledge\Law Wiki`
2. Start at `wiki/overview.md` or `wiki/index.md`
3. Follow `[[wikilinks]]` into topic/year/website indexes, then source pages, then raw text

Graph view works when the vault root is this folder (so `raw/` and `wiki/` are both visible).
For a research-focused graph, add this Obsidian filter:
`-path:raw -path:wiki/indexes`

## Folder map

```
raw/documents/     immutable full texts, one file per CSV row
raw/pdfs/          immutable original PDFs added by folder
wiki/sources/      one digest page per document (summaries start unverified)
wiki/entities/     source organizations (and later courts, parties)
wiki/concepts/     CSV topics (and later doctrines)
wiki/families/     duplicate-text and related-document families
wiki/instruments/  legislation and other cited legal instruments
wiki/cases/        canonical case pages when separately enriched
wiki/memos/        reusable research memoranda
wiki/indexes/      dimension hubs and paginated catalogs
wiki/index.md      short hub
wiki/overview.md   corpus statistics
wiki/log.md        append-only history
templates/         page templates
scripts/           CSV importer
data/catalog.jsonl machine catalog
AGENTS.md          schema for LLM sessions
site/              public Astro search and knowledge-map portal
```

## Import the CSV corpus

Each row in `C:\Users\Dong\Downloads\df_organized.csv` is one document (5,156 rows). The ~100 MB CSV is **not** copied into the vault.

```powershell
C:\Users\Dong\miniconda3\python.exe scripts\import_csv.py --csv C:\Users\Dong\Downloads\df_organized.csv
```

Reruns are idempotent. Exact CSV topic labels are normalized through
`data/topic-map.json` while retained as `topic_raw`. Generated pages carry
fingerprints: unchanged pages are skipped, and modified or enriched source,
entity, and concept pages are reported as protected conflicts and never
overwritten. Index dimensions paginate after 200 source links while keeping
the original hub path stable.

Do not filter on `is_empty`. Duplicate full texts stay as separate documents.

## Public web portal

The portal is a static GitHub Pages site. It provides full-text Pagefind
search, metadata filters, folder browsing, document pages, PDF viewing, and an
interactive map generated from accepted connections.

```powershell
cd site
npm install
npm run build
npm run preview
```

Generated web data and deployment artifacts are ignored by Git and rebuilt
from the authoritative Law Wiki on every deployment.

### Add PDFs later

Place each original under:

```text
raw/pdfs/<website>/<year>/<optional-subfolder>/<filename>.pdf
```

Then run:

```powershell
C:\Users\Dong\miniconda3\python.exe -m pip install -r requirements.txt
C:\Users\Dong\miniconda3\python.exe scripts\import_pdfs.py
cd site
npm run build
```

The importer never edits a supplied PDF. It writes extracted text and a source
page, protects changed content, and records the original path in
`data/pdf-catalog.jsonl`. GitHub rejects individual files of 100 MB or more;
such PDFs need external object storage before publication.

## Tests

```powershell
C:\Users\Dong\miniconda3\python.exe -m unittest discover -s tests
C:\Users\Dong\miniconda3\python.exe scripts\verify_wiki.py
```

## Connection graph pilot

The connection pipeline is deliberately limited to 250 documents:

```powershell
C:\Users\Dong\miniconda3\python.exe scripts\extract_legal_signals.py
C:\Users\Dong\miniconda3\python.exe scripts\select_pilot.py --count 250 --seed 46
C:\Users\Dong\miniconda3\python.exe scripts\extract_legal_signals.py --manifest data\enrichment\pilot-manifest.jsonl
# Run ten isolated 25-document extraction batches and two independent reviews.
C:\Users\Dong\miniconda3\python.exe scripts\build_connection_graph.py --extraction ... --reviewer ... --reviewer ...
C:\Users\Dong\miniconda3\python.exe scripts\lint_wiki.py --expected 5156
```

Accepted edges are stored in `data/connections.jsonl`; rejected, disputed, and
summary-only candidates remain in `data/enrichment/review-queue.jsonl`.
Acceptance means the provenance and model-review gates passed. It does not set
the legal `verification` field to `verified`.

## Example prompts

**Ingest (after adding a raw file):**
> Read AGENTS.md. Ingest `raw/documents/...`. Update the source page, related entities/concepts, indexes, and log. Cite pinpoints. Mark anything you did not verify.

**Query:**
> Read wiki/index.md first. What does this corpus say about [issue]? Cite source pages and raw documents. Separate facts from analysis. If the wiki does not support a claim, say so.

**Lint:**
> Health-check the wiki: orphans, missing citations, unverified pages used as authority, raw/source/catalog mismatches, stale as_of dates. Append findings to wiki/log.md.

## Confidential work

Do not store client files, matter notes, or privileged communications in this vault.
