# Minutas security checklist (development)

Scope: the private development stack in `eu-west-1`. Fictional cases and published decisions only, until the CSM validates a production system operated or contracted by the IGFEJ or the CSM.

This checklist is an engineering control list. It is not a CSM validation, not an AI Act conformity assessment, and not legal advice.

| Control | Requirement | Status in this design |
|---|---|---|
| MFA required | Cognito MFA required, TOTP | Specified. First login is incomplete until TOTP is enrolled |
| No self sign-up | Admin-created users only | Specified. `admin-create-user` is the only path in [DEPLOY.md](DEPLOY.md) |
| KMS on the cases bucket | `LW_CASES_BUCKET` uses SSE-KMS | Specified for case inputs, packets, and exports. Corpus-bucket key policy is **a confirmar** in CDK; the public plan also asks for KMS on the corpus |
| Private buckets and OAC | Web bucket is private; CloudFront uses OAC; cases and corpus buckets are not public | Specified. SPA fallback is `index.html`. `/api/*` goes to the HTTP API with no cache and forwards `Authorization` |
| JWT on all API routes | Every `/api` route requires the Cognito JWT | Specified. Claims are read from `event.requestContext.authorizer.jwt.claims` |
| Owner checks | Item owner must equal claim `sub`, otherwise 404 | Specified. Keys are `USER#{sub}` and draft meta stores `owner` |
| No case text in logs | Logs and audit items store ids and hashes | Specified for the audit item (`textSha256`, `promptSha256`, `sourceIds`). Confirm in code review that Lambdas do not print request bodies. **A confirmar** until that review is recorded |
| Least-privilege IAM | Each Lambda role can touch only its table, buckets, state machine, and the `eu.` Bedrock profile | Specified as a deploy rule. The concrete policies are **a confirmar** in the CDK diff |
| `eu.` Bedrock only | `LW_MODEL_ID` defaults to `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | Specified. Confirm destinations with `aws bedrock get-inference-profile` before use |
| CloudTrail | Account trail for management events | Specified on the public plan and in this stack's operating checks. Trail name and retention are **a confirmar** |
| No WAF in lean mode | Accepted risk, development only | Accepted. Rationale below |
| Data retention | A defined deletion period | **To define** with the CSM before any real-data pilot. No retention period is set for this dev stack |

## Accepted risk: no WAF in lean mode

The public plan draws AWS WAF in the access layer and estimates development infrastructure at 20 to 50 USD/month including WAF. The development contract chooses lean mode: no WAF, no S3 Vectors in v1, and a 10 USD/month budget alarm.

That omission is accepted only for this private development account, and only while the data are fictional cases and published decisions.

Compensating controls that are in the design:

- Self sign-up is off, so an anonymous visitor cannot create an account.
- TOTP MFA is required for every user.
- The web bucket is private behind CloudFront OAC.
- Every API route requires a JWT, and every item is checked against the caller `sub`.
- Case creation requires `fictional: true`.
- Bedrock runs only when an authenticated user queues a draft, or when someone explicitly runs a live eval.

Residual risk: the CloudFront distribution is on the public internet without a web application firewall, so volumetric noise and abusive calls to the static site are possible, and the managed login page can be hammered. MFA and disabled sign-up limit account takeover. The 10 USD budget alarm is the cost backstop. This acceptance does not carry over to a production deployment. Production is redesigned with the IGFEJ or the CSM, and WAF is back on the table there.

## Data handling rules that support the checklist

- The public GitHub Pages site never receives case files. The private stack is not indexed as a public site.
- TLS in transit. SSE-KMS at rest on the cases bucket.
- Generation happens only when the user asks for a draft (CSM recommendations 6.5, 9.5, and 10 on the plan page: generation at the judge's will, free edit, traceability, no reuse for a different purpose, declaration on the decision).
- Audit actions are `generate`, `accept`, `edit`, `reject`, and `export`.
- Export appends the CSM sentence and stays blocked until review is complete.
- AWS states that Bedrock inputs are not used to train models. The plan page says to keep traffic in EU regions via `eu.` profiles. Confirm the live profile anyway.
- Retention and automatic deletion are to be defined with the CSM (plan page, security section, and Law 34/2009 as read there). Until that decision, operators delete development objects by hand, using the incident steps in [RUNBOOK.md](RUNBOOK.md) if a real file appears.

## Related drafts

- [Technical documentation (pt-PT)](ai-act-documentacao-tecnica.md)
- [DPIA draft (pt-PT)](aipd-rascunho.md)
- [Fundamental rights impact draft (pt-PT)](avaliacao-impacto-direitos-fundamentais-rascunho.md)
