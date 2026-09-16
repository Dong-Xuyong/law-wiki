# Law Wiki — Schema

This document governs how the LLM maintains the law wiki. Read it at the start of every ingest, query, or lint session.

## Purpose

Build a compounding legal research knowledge base. Immutable full texts live in `raw/` (never edited by hand). Digests, entity pages, concept pages, and cross-references live in `wiki/` (LLM-owned, except machine-generated catalogs). Open `Law Wiki/` as an Obsidian vault.

This vault is a **research aid**, not legal advice, not a court filing, and not a substitute for primary authorities or a lawyer. Confidential client, matter, and privileged records do **not** belong here — they need a separate secured design.

## Folder map

```
Law Wiki/
├── AGENTS.md              # This file — schema and workflows
├── README.md              # Human setup
├── scripts/import_csv.py  # Bulk importer for df_organized.csv
├── data/                  # Machine catalog (catalog.jsonl)
├── templates/             # Page templates for incremental ingest
├── raw/                   # Immutable source documents
│   ├── documents/<website>/<year>/<id>.md
│   └── pdfs/<website>/<year>/<filename>.pdf
├── site/                  # Public Astro portal generated from the wiki
└── wiki/                  # LLM-maintained Obsidian vault
    ├── index.md           # Short catalog — shards hold full lists
    ├── overview.md        # Corpus snapshot, not legal conclusions
    ├── log.md             # Append-only chronological record
    ├── sources/           # One digest page per document
    ├── cases/             # Canonical case pages
    ├── instruments/       # Statutes, regulations, and cited instruments
    ├── families/          # Duplicate-text and related-document groups
    ├── memos/             # Reusable research memoranda
    ├── entities/          # Organizations, courts, parties, authors
    ├── concepts/          # Topics, doctrines, tests
    └── indexes/           # Sharded lists by topic, website, year, folder
```

## Raw layer rules

- **Never modify** files in `raw/` except by re-running `scripts/import_csv.py`.
- Original PDFs supplied incrementally live in
  `raw/pdfs/<website>/<year>/<filename>.pdf`. They are immutable after ingest;
  `scripts/import_pdfs.py` is the only workflow allowed to create their
  extracted `raw/documents/` and `wiki/sources/` counterparts.
- Each CSV row is one document, including rows whose full text is duplicated and rows with `is_empty=True`.
- Do **not** filter on `is_empty`. The flag is retained as original metadata and is often wrong.
- Document id: `law_` + first 16 hex chars of SHA-256(`lawwiki:v1\0{website}\0{folder}\0{filename}`) after Unicode NFC, trim, slash-normalization, and case-fold.
- `content_hash` is SHA-256 of the full `text` and is **not** the document id.
- If a rerun sees a different `content_hash` for an existing raw file, report it. Do not overwrite unless `--force-raw`.

## Wiki page conventions

### Frontmatter (all wiki pages)

Use valid, closed YAML frontmatter (`---` open and close). Never put markdown headings inside frontmatter.

**Common fields:**

```yaml
---
tags: [sources, topic-slug, website-slug]
created: YYYY-MM-DD
updated: YYYY-MM-DD
aliases: [Display Name]
verification: unverified | verified | disputed | superseded
jurisdiction: Portugal | unknown
as_of: YYYY | unknown
---
```

### File naming

| Layer    | Pattern                                      | Example                                      |
| -------- | -------------------------------------------- | -------------------------------------------- |
| raw      | `raw/documents/<website>/<year>/<id>.md`     | `raw/documents/caccl/2022/law_ab12cd34ef56.md` |
| sources  | `wiki/sources/<file-slug>--<id>.md`          | `wiki/sources/sent-82--law_ab12cd34ef56.md`  |
| entities | `wiki/entities/<slug>.md`                    | `wiki/entities/caccl.md`                     |
| concepts | `wiki/concepts/<slug>.md`                    | `wiki/concepts/garantias-defeitos.md`        |

Use lowercase hyphen slugs. Store the stable `id` in frontmatter and `aliases`.

### Required legal metadata (source pages)

| Field                 | Bulk-import default                         |
| --------------------- | ------------------------------------------- |
| `jurisdiction`        | `Portugal` with `jurisdiction_source: corpus-default` |
| `authority_level`     | `unknown` until classified                  |
| `citation`            | Original filename (provisional)             |
| `legal_status`        | `unknown`                                   |
| `as_of`               | CSV `year`                                  |
| `verification`        | `unverified`                                |
| `enriched`            | `false` until a human/LLM checks the raw text |
| `enrichment_state`    | `imported-unverified`                       |
| `raw`                 | Path to the immutable file                  |

Do not invent official citations, courts, parties, holdings, or subsequent history.
Source frontmatter also records `document_type`, `process_number`, `case`,
`forum`, `decision_date`, `sectors`, `doctrines`, `cited_instruments`,
`outcome_status`, duplicate/family links, and `extractor_version`. Unknown
legal facts remain visibly `unknown`; empty arrays mean that nothing was
extracted, not that nothing exists.

### Controlled topic metadata

- Preserve the exact CSV label in `topic_raw`.
- Normalize only exact labels found in `data/topic-map.json`.
- Treat mapped `sector` and `categories` as controlled filing metadata, not
  legal conclusions. Unmapped labels remain visible as `unmapped`.

### Generated-page safety

- Importer-owned source, entity, concept, family, overview, and index pages
  carry `generated_fingerprint`.
- An unchanged valid fingerprint permits regeneration; identical output is
  skipped. A missing/invalid fingerprint, manual edit, or enriched page is a
  protected conflict: report it and do not overwrite it.
- Delete stale pages only when they are positively identified as unmodified
  importer-generated output. Never delete an unknown or modified page.

### Source page sections

Follow `templates/source.md`:

1. Status (verification + not-legal-advice)
2. Import flags (optional)
3. Summary (CSV digest until replaced by a verified digest)
4. Source metadata
5. Key holdings / issues — only after reading the raw text
6. Entities mentioned
7. Concepts
8. Pinpoint quotations
9. Related sources
10. Raw source link

### Entity and concept pages

- Entities: `type: organization | court | party | person | statute | agency`
- Concepts: definition, evolution, sources, related concepts
- Bulk import only seeds CSV `website` organizations and `Topic` labels. Deeper doctrines, courts, and parties are incremental.

## Legal reliability rules

- Every legal proposition and quotation needs a **pinpoint** to a raw document (filename, section, page, or paragraph if known).
- Prefer primary text in `raw/` over summaries, indexes, or memory.
- Separate **sourced facts** from **analysis**. Label analysis explicitly.
- Visible labels for `unknown`, `disputed`, `superseded`, and `unverified`.
- Do not silently resolve conflicts. Note both authorities and the dates/`as_of` values.
- Subsequent treatment, amendments, and stale-law checks belong in lint, not in optimistic rewrites.
- Imported `summary` text is **unverified** until checked against the full text. Never present it as a holding.

## Operations

### Ingest (CSV bulk)

```
C:\Users\Dong\miniconda3\python.exe scripts\import_csv.py --csv C:\Users\Dong\Downloads\df_organized.csv
```

The importer:

1. Parses the CSV with Python's csv module (multiline fields; raised field-size limit).
2. Writes one raw file and one source page per row.
3. Maps exact Topic labels, retaining `topic_raw` and controlled sectors/categories.
4. Seeds entity/concept/family pages and generates dimension home pages.
5. Paginates dimensions above 200 links with stable hubs and parent/prev/next navigation.
6. Regenerates safe generated pages and `data/catalog.jsonl`; skips identical output.
7. Protects modified/enriched source, entity, and concept pages and reports conflicts.
8. Reports raw `content_hash` changes instead of overwriting.

### Ingest (single document)

When the user drops a new file into `raw/` or asks to ingest one source:

1. Read the raw file. Never edit it.
2. Discuss takeaways if the user is present.
3. Create or update `wiki/sources/<slug>.md` from `templates/source.md`.
4. Create or update entities and concepts actually supported by the text.
5. Update the relevant shard indexes, `wiki/index.md` counts, and `wiki/overview.md` only if the big picture changed.
6. Append `wiki/log.md`.
7. Set `enriched: true` only after the digest is checked against the raw text.

### Ingest (folder-based PDFs)

1. Place originals under `raw/pdfs/<website>/<year>/`; nested folders below
   the year are permitted and retained in catalog metadata.
2. Run `scripts/import_pdfs.py`. It computes stable IDs from the website,
   derived folder, and filename, extracts text without modifying the PDF, and
   records rows in `data/pdf-catalog.jsonl`.
3. Existing raw text with a changed content hash and manually modified source
   pages are protected conflicts and must not be overwritten.
4. Install extraction support from `requirements.txt`. Empty extraction stays
   visible and unverified; do not infer that the PDF has no content.

### Public web portal

1. Run `scripts/build_web_catalog.py` before the Astro build. It merges the
   base and PDF catalogs and emits disposable data under `site/src/generated`
   and `site/public/data`.
2. The public site indexes titles, metadata, imported summaries, and full raw
   text. Verification labels and the research-aid warning must remain visible.
3. Only accepted assertions from `data/connections.jsonl` may appear as legal
   graph relations. Folder/topic/website edges are metadata navigation.
4. PDFs are copied into the deployment artifact, not duplicated in tracked
   source folders. Files at or above GitHub's file limits require external
   storage rather than Git LFS, which GitHub Pages does not serve as PDF data.

### Connection enrichment (pilot)

1. Run `scripts/extract_legal_signals.py` to create deterministic candidates.
2. Run `scripts/select_pilot.py --count 250 --seed 46`; do not expand the
   sample unless the pilot quality gates pass.
3. Generate bounded packets with
   `scripts/extract_legal_signals.py --manifest data/enrichment/pilot-manifest.jsonl`.
4. Extraction batches may use packet windows and deterministic candidates, but
   never CSV summaries as hard evidence. Raw text spans use normalized-LF
   Python code-point offsets and half-open `[start, end)` coordinates.
5. Two independent reviewers adjudicate model assertions. Store provisional,
   disputed, rejected, and summary-only assertions in the review queue.
6. `scripts/build_connection_graph.py` writes accepted assertions to
   `data/connections.jsonl` and marker-delimited source/hub sections.
7. Model-reviewed graph acceptance does not change `verification` to
   `verified`; only the human makes that legal-reliability decision.

Canonical resolver keys:

- Case: normalized forum plus validated process number.
- Instrument: jurisdiction, type, and number/year.
- Authority: ECLI when present; otherwise court, process number, and date.
- Generic or redacted natural persons are not global entities. Clearly named
  organizations may be linked; claimant/respondent roles remain case-local.

Accepted source-to-source links are sparse: no more than three per source, each
with a concrete reason such as same case, shared authority/instrument/doctrine,
version/addendum, exact duplicate, or high-confidence template sibling.

### Query

1. Read `wiki/index.md`, then the matching shard under `wiki/indexes/`.
2. Read source, entity, and concept pages.
3. Open the raw document before stating law.
4. Answer with wikilinks and pinpoint citations.
5. If the answer is reusable, file it (concept comparison, research memo) and log it.
6. If the wiki does not support the claim, say so. Do not fill gaps from training data as if they were in this corpus.

### Lint

Periodically or on request:

1. Find contradictions between source digests and raw text.
2. Find orphan pages with no inbound `[[links]]`.
3. Find concepts or entities mentioned in sources but missing a page.
4. Flag stale `as_of` / year claims and missing subsequent treatment.
5. Flag missing pinpoint citations and unverified pages cited as verified.
6. Check broken wikilinks and raw/source/catalog count mismatches.
7. Append a lint entry to `wiki/log.md`.

Run `scripts/lint_wiki.py --expected 5156` after graph materialization. Every
accepted assertion must have a valid target and provenance hash/span. Do not
process the remaining corpus unless the pilot report records at least 95%
reviewed hard-link precision, valid evidence for every accepted assertion, and
clean link/orphan checks.

## Index and log

`wiki/index.md` is a short hub. Every dimension has a canonical
`wiki/indexes/by-*/index.md` home. Full listings include topic, website, year,
folder, sector, and category dimensions. Dimension values over 200 links use
child pages while retaining the original value hub path.

Recommended Obsidian graph filter: `-path:raw -path:wiki/indexes`.

`wiki/log.md` is append-only:

```
## [YYYY-MM-DD] ingest  Title
## [YYYY-MM-DD] query   Question summary
## [YYYY-MM-DD] lint
```

## Human vs LLM roles

| Human                         | LLM                                      |
| ----------------------------- | ---------------------------------------- |
| Choose sources and questions  | Write and maintain wiki pages            |
| Guide emphasis during ingest  | Summarize, cross-reference, file         |
| Decide what is verified       | Query with citations; flag uncertainty   |
| Browse Obsidian               | Lint; keep index/log/catalog current     |
| Legal judgment and advice     | Never — research aid only                |
