---
tags: [reports, pilot-quality, connections]
created: 2026-09-15
updated: 2026-09-15
verification: unverified
---

# Pilot connection-graph quality

**Gate result: PASS**. This is a technical and model-review quality gate, not legal verification or legal advice.

## Scope and coverage

- Pilot documents: 250 of 5,156.
- Extraction batches: 10 × 25 documents.
- Websites / raw topics / years: 6 / 22 / 11.
- Short-text quality gates: 28.

## Extraction and review

- Candidate assertions: 1830.
- Candidate predicates: `about_doctrine` 45, `about_sector` 184, `about_topic` 250, `cites_authority` 4, `cites_instrument` 352, `cites_provision` 31, `decided_by` 191, `document_of` 187, `exact_duplicate_of` 52, `has_outcome` 135, `mentions_entity` 116, `published_by` 250, `same_case_as` 6, `semantically_similar_to` 4, `template_sibling_of` 23.
- Independently reviewed non-deterministic assertions: 1110.
- Reviewer agreement: 977/1110 (88.0%); disagreements: 133.
- Both accepted: 785; both rejected: 192.
- Accepted assertions: 1275 (`content-hash` 52, `grok-4.6` 541, `metadata` 668, `regex` 14).
- Review queue: 555 (`disputed` 133, `rejected` 422).
- Summary-only assertions: 0. Extraction packets contained no CSV summary text, so no summary-only claim could become a hard edge.

## Provenance and graph integrity

- Accepted assertions with valid target evidence: 1275/1275.
- Lint: clean; errors 0, warnings 0.
- Canonical graph hubs: 122.
- Raw/source/catalog parity: 5156 / 5156 / 5156.
- Deterministic rerun aggregate SHA-256: `2ae4f01b240395452a1ba3b1146709b57b99929c7f4432637c7c601b929da6f0` (identical across 2 runs).

## Reproducible precision spot check

- Sample: 100 accepted assertions, selected by `SHA-256(law-wiki-pilot-precision-v1:assertion_id)` with at least three per predicate when available.
- Audit completion: 100/100.
- Judgments: `correct` 100.
- Conservative precision (uncertain/missing count as failures): 100.0%.
- The audit is an independent model check of whether the cited evidence directly supports the edge. It is not human legal verification.

## Accepted edge examples

- `about_sector`: `document:law_e6a2f11808d3422f` → `sector:energy`; evidence `Eletricidades e gas naturais`.
- `about_topic`: `document:law_f4b5f8a282472df4` → `topic:viagens-organizadas`; evidence `Viagens Organizadas`.
- `cites_authority`: `document:law_7b94c3e3347f17c8` → `authority:stj:708/14.3T80AZ-A.P1.S1:2021-02-23`; evidence `Supremo Tribunal de Justiça, no proc. n.º 708/14.3T80AZ-A.P1.S1, de  23/02/2021`.
- `cites_instrument`: `document:law_8c4fed5753cffb9c` → `instrument:pt:lei:24/1996`; evidence `Lei 24/96`.
- `cites_provision`: `document:law_c28341546fd775a5` → `provision:pt:codigo-civil:402`; evidence `artigo 402º, do Código Civil`.
- `decided_by`: `document:law_86fa6cfac30858ba` → `forum:pt:cniacc`; evidence `Tribunal Arbitral do CNIACC`.
- `exact_duplicate_of`: `document:law_8a70e4d9960235d6` → `document:law_5e880240beb81480`; evidence `07945cbed7f315d405079e52e2c5d7cf04742a91be3c7784c80e40ae8bb767d1`.
- `has_outcome`: `document:law_598ed2b3a3a54e4e` → `outcome:procedente`; evidence `Julgo a ação procedente`.
- `mentions_entity`: `document:law_efa75268e2c7eb88` → `organization:cniacc`; evidence `CNIACC`.
- `published_by`: `document:law_c28341546fd775a5` → `organization:triave`; evidence `Triave`.

## Quality gates

- PASS — sample complete.
- PASS — precision at least 95.
- PASS — all accepted evidence valid.
- PASS — lint clean.
- PASS — pilot only.
- PASS — deterministic rerun.

## Scale decision

Pilot gates passed. The remaining corpus is still not processed in this task; scale-out requires a separate explicit decision.
