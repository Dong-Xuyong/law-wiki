# Minutas

Minutas is a private development application in AWS `eu-west-1`. It drafts a Portuguese court decision from a fictional case or a published decision, then stops for paragraph-by-paragraph human review before a DOCX export.

The first drafting target is compensation under Regulation (EC) No 261/2004 (air passenger rights). The judge's questionnaire answer on the first real decision type is still open. Treat 261/2004 as the development target, and treat the judge's choice as still to be confirmed.

The public plan is [the implementation plan](https://dong-xuyong.github.io/law-wiki/plano/) (16 October 2026). Interface rules live in `app/CONTRACTS.md`. This file describes the development app. It is not legal advice and it is not permission to use the tool on a real case.

## Scope limits

Until the Conselho Superior da Magistratura (CSM) validates the tool, the app accepts only fictional cases and published decisions. CSM recommendation 8 (8 April 2026) allows non-supplied tools for study on open sources. Judicial data stays out. Procedural material, if it is ever used in a test, is anonymised first.

Creating a case requires `fictional: true`. The API rejects anything else with `fictional_required`. The interface shows a banner. Every rendered page keeps this marker:

`MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA`

Legal authorities come only from the local corpus (`raw/documents/**`, listed in `data/catalog.jsonl` and `data/open-sources-catalog.jsonl`). The model is not a source of law.

A fact is proved only with basis `common`, `admission`, or `procedural_record`. A draft is not final until every paragraph is reviewed. There is no "accept all" action. Export stays blocked while any paragraph is unreviewed or a required section would be empty. The DOCX then appends:

`Decisão produzida com o auxílio de sistema de IA, de acordo com as recomendações do CSM. Integralmente revisto pelo signatário.`

The development account is a personal AWS account for building and demonstration. Recommendations 4 and 6 say judges use AI systems and drafts supplied by the case-management system or by the CSM. Production, if it happens, sits with the IGFEJ or the CSM after written validation. See the [CSM dossier outline](dossie-csm-esboco.md).

## Components

| Path | Role |
|---|---|
| `app/engine/` | Packet validation, DOCX render, citation checks |
| `app/engine/draft/` | Draft pipeline. Bedrock only through an `eu.` inference profile |
| `app/engine/retrieve/` and `app/ingest/index_fts.py` | Literal search on a SQLite FTS5 index |
| `app/ingest/sources/` | Open corpus, including the 261/2004 material as it is added |
| `app/api/` | HTTP API and the Step Functions draft worker (Python 3.12 Lambdas) |
| `app/web/` | Review UI in European Portuguese |
| `app/eval/` | Offline evaluation, plus an explicit live mode |
| `app/infra/` | CDK stack for the development environment |
| `docs/app/` | These operating and compliance drafts |

Lean mode, for this development stack: no AWS WAF, no S3 Vectors in v1, a 10 USD/month budget alarm, and Bedrock only when a user generates a draft or someone runs an explicit `--live` eval. The public plan still lists WAF and S3 Vectors in the target architecture. Those are for a later, publicly operated deployment.

Default model id: `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` (`LW_MODEL_ID`).

## Tests and evaluation

From the repository root, with Python 3.12 (`C:\Users\Dong\miniconda3\python.exe` on this machine):

```powershell
python -m unittest discover -s app/tests -t .
python -m app.eval run --offline
```

`app/tests/` is the app suite. The repository `tests/` directory is the public Pages CI suite and does not install these dependencies.

`--offline` must not call Bedrock. A live model run is separate and explicit: `python -m app.eval run --live`. Live runs spend about 1 to 1.50 USD per draft on the October 2026 planning estimate. The evaluation metrics themselves are still to be filled in. See [technical documentation](ai-act-documentacao-tecnica.md).

## Other documents

- [Deploy](DEPLOY.md): build, `eu-west-1` deploy, first user, teardown, cost
- [Runbook](RUNBOOK.md): checks, logs, failed drafts, users, incidents, cost spikes
- [Security](SECURITY.md): development security checklist
- [Technical documentation draft (pt-PT)](ai-act-documentacao-tecnica.md): AI Act Annex IV working draft
- [DPIA draft (pt-PT)](aipd-rascunho.md): GDPR Article 35 draft for a future real-data pilot
- [Fundamental rights impact draft (pt-PT)](avaliacao-impacto-direitos-fundamentais-rascunho.md): AI Act Article 27 draft
- [CSM dossier outline (pt-PT)](dossie-csm-esboco.md): outline for the CSM/GAIA and the IGFEJ
