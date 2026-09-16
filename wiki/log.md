# Wiki Log

Append-only chronological record of ingests, queries, and lint passes.

## [2026-09-11] ingest  df_organized.csv

- Input: `C:\Users\Dong\Downloads\df_organized.csv` (102448958 bytes, sha256 `93708e7ea6e73db036bd4726bf632a5e27132900364bc0b8b3b7e7ae5cf8a71c`)
- Rows: 5156
- Raw written: 5156; unchanged: 0; content-change reports: 0
- Sources written: 5156; skipped enriched: 0
- Duplicate full-text groups kept separate: 26 (52 rows)
- Short texts (≤500 chars): 28
- Concepts seeded: 22; entities seeded: 6
- Updated: wiki/index.md, wiki/overview.md, wiki/indexes/*, data/catalog.jsonl

## [2026-09-11] ingest  df_organized.csv

- Input: `C:\Users\Dong\Downloads\df_organized.csv` (102448958 bytes, sha256 `93708e7ea6e73db036bd4726bf632a5e27132900364bc0b8b3b7e7ae5cf8a71c`)
- Rows: 5156
- Raw written: 0; unchanged: 5156; content-change reports: 0
- Sources written: 5156; skipped enriched: 0
- Duplicate full-text groups kept separate: 26 (52 rows)
- Short texts (≤500 chars): 28
- Concepts seeded: 22; entities seeded: 6
- Updated: wiki/index.md, wiki/overview.md, wiki/indexes/*, data/catalog.jsonl

## [2026-09-12] ingest df_organized.csv

<!-- import-sha256:93708e7ea6e73db036bd4726bf632a5e27132900364bc0b8b3b7e7ae5cf8a71c -->
- Rows: 5156
- Raw written: 0; unchanged: 5156; changes protected: 0
- Sources written: 5156; unchanged: 0
- Protected wiki conflicts: 0

## [2026-09-15] lint connection-graph pilot

- Pilot: 250 documents in 10 extraction batches.
- Assertions: 1,275 accepted; 555 retained in the review queue.
- Provenance: 1,275/1,275 accepted assertions validated.
- Graph lint: 0 errors; 0 warnings; 122 canonical hubs.
- Raw/source/catalog parity: 5,156 / 5,156 / 5,156.
- Precision audit: 100/100 correct after tightening direct-support rules.
- Quality gate: passed; remaining-corpus scale-out not performed.

## [2026-09-16] query Compensação Regulamento 261/2004 — atraso/cancelamento OPO–MXP

- Question: indemnização de 600 € e danos conexos (reencaminhamento, hotel, lounge, horas de trabalho) após cancelamento de voo intra-UE.
- Wiki hubs: [[instruments/eu-regulamento-261-2004]], [[concepts/atraso-e-ou-cancelamento-de-voo]].
- Primary pinpoints: CICAP 748/2023 e 1455/2023 (€250 até 1 500 km); CICAP 1282/2021 (€400 > 1 500 km intra-UE); Triave 1675/2022 (art. 12.º + voo substituto e perdas salariais); CACCL Sent. 351.TA (recusa de reencaminhamento); CICAP 1584/2022 e CACCL Sent. 383.TA (Sturgeon/Nelson).
- Gaps: número de processo e identificação nominativa da reclamante não constam; o corpus não contém o texto oficial consolidado do Regulamento nem medição independente OPO–MXP; URLs EUR-Lex apenas nas formas OCR dos originais.
