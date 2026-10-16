# Tranche t001 reviewer brief

Two reviewers work independently. Reviewer 1 writes only `reviewer-1.jsonl`. Reviewer 2 writes only `reviewer-2.jsonl`. Do not open the other reviewer's file. Do not edit extractor files, packets, the manifest, raw documents, or `data/connections.jsonl`.

This is a model review of provenance. It does not set legal `verification` to `verified`.

## Inputs

All paths are relative to the Law Wiki repository root.

- Manifest (100 documents): `data/enrichment/tranches/t001/manifest.jsonl`
- All packets: `data/enrichment/tranches/t001/packets.jsonl`
- Batch packets: `packets-01.jsonl`, `packets-02.jsonl`, `packets-03.jsonl`, `packets-04.jsonl` in the same folder
- Extractors: `extractor-01.jsonl` through `extractor-04.jsonl` in the same folder

Read each extractor row against its packet. Batch 01 is the first 25 manifest documents, then 02, 03, and 04.

## Output

| Reviewer | File | `reviewer` value |
| --- | --- | --- |
| 1 | `data/enrichment/tranches/t001/reviewer-1.jsonl` | `grok-reviewer-1` |
| 2 | `data/enrichment/tranches/t001/reviewer-2.jsonl` | `grok-reviewer-2` |

UTF-8, LF newlines, one JSON object per line, no wrapper object. Same four fields as `data/enrichment/pilot/reviewer-1.jsonl`:

```json
{"assertion_id": "conn_...", "decision": "accepted", "reason": "Quote names CICAP in the tribunal heading.", "reviewer": "grok-reviewer-1"}
```

- `decision` is exactly `accepted` or `rejected`.
- `reason` is one or two sentences that point at the quote.
- Sort lines by `assertion_id`.
- One line per raw-span assertion, and no other lines.

## What to review

Review every assertion whose `provenance.kind` is `raw-span`.

Leave `metadata-field` assertions (`published_by`, `about_topic`) out of the file. The builder accepts those after the catalog value and hash match. This tranche has no `content-hash` assertions.

Raw-span counts, which are the line counts of your file:

| Batch file | Documents | Assertions | Raw spans to review |
| --- | ---: | ---: | ---: |
| `extractor-01.jsonl` | 25 | 148 | 98 |
| `extractor-02.jsonl` | 25 | 143 | 93 |
| `extractor-03.jsonl` | 25 | 136 | 86 |
| `extractor-04.jsonl` | 25 | 139 | 89 |
| Total | 100 | 566 | 366 |

A missing `assertion_id` is not an acceptance. Both reviewers have to accept a raw-span edge before it can enter `data/connections.jsonl`.

## Evidence rules

Offsets are Python Unicode code points on the normalized-LF payload after the level-2 heading `Full text`. One framing newline after that heading is not part of the payload. Coordinates are half-open `[start, end)`. The quote must equal `payload[start:end]`, and that slice must sit inside a packet window (`header`, `party`, `applicable_law`, `citation`, or `disposition`).

CSV summaries and source-page summaries are not evidence.

Accept a raw-span edge only when the quote itself states the predicate:

- `cites_instrument` / `cites_provision`: the quote is the cited instrument or article. The object key keeps the jurisdiction, type, and number/year as written. A 2-digit year stays 2 digits. `Decreto-Lei`, `Dec. Lei`, and a line-broken `Decreto- / Lei` are `instrument:pt:decreto-lei:...`, not an ordinary lei.
- `decided_by`: the quote contains the forum token (`cniacc`, `cicap`, `ciab`, `triave`, or `caccl`) and an adjudicative word (`tribunal`, `arbitragem`, or `julgado de paz`).
- `document_of`: the key is `case:pt:{forum}:{process}`. That same quote contains the forum token, the process number, and an adjudicative word.
- `has_outcome`: the quote is the operative result in the disposition or in a `julga-se` / `julgo` / `decide-se` sentence, not the claimant's request.
- `about_sector` / `about_doctrine`: the quote uses those words for this dispute.
- `mentions_entity`: the quote names an organization. Generic or redacted natural persons are not global entities. Claimant and respondent roles stay case-local.
- `same_case_as`: the builder rejects every same-case link, because one span cannot prove both documents. Reject it.
- Source-to-source links (`exact_duplicate_of`, `same_case_as`, `template_sibling_of`, `semantically_similar_to`) need a concrete reason and stay at or under 3 per source. This tranche emitted none.

Canonical keys, from `AGENTS.md`:

- Case: normalized forum plus validated process number.
- Instrument: jurisdiction, type, and number/year.
- Authority: ECLI when present; otherwise court, process number, and date.

The quality bar is at least 95% reviewed hard-link precision. When the quote does not directly support the key, reject it.

## After both files exist

The supervisor runs:

```powershell
C:\Users\Dong\miniconda3\python.exe scripts\graph_tranche.py build
```

That adjudicates the pilot extractors and reviewers together with this tranche, and it keeps the pilot's accepted edges.
