# Deploy Minutas (development, eu-west-1)

This is the development environment only. It holds fictional cases and published decisions. It is not the production system, and it is not a tool supplied by the case-management system or by the CSM.

Run the commands from the Law Wiki repository root unless a step says otherwise. On this machine use `C:\Users\Dong\miniconda3\python.exe` as `python`. Region is `eu-west-1` for every AWS call.

Stack output names (bucket, user pool, distribution URL) come from CDK. The `app/infra` package was not in the tree when this page was written, so those names are marked **a confirmar** until `cdk deploy` prints them.

## 1. Prerequisites

1. Sign in to the project account with `aws login`. Use a non-root deploy user or role. Root is the wrong principal for CloudFormation, IAM, and KMS changes. The exact permission set is **a confirmar** with the infra owner; it needs to deploy the CDK stack (CloudFormation, S3, Lambda, IAM, Cognito, CloudFront, API Gateway, Step Functions, DynamoDB, KMS, CloudTrail, Budgets) and to call Bedrock in `eu-west-1`.
2. Set the region:

```powershell
$env:AWS_REGION = "eu-west-1"
$env:AWS_DEFAULT_REGION = "eu-west-1"
aws sts get-caller-identity
```

3. In the Bedrock console, in `eu-west-1`, request model access for Anthropic Claude Sonnet 4.5 and use the EU inference profile. Then confirm the profile and its destination regions:

```powershell
aws bedrock get-inference-profile --region eu-west-1 --inference-profile-identifier eu.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Read the response. The public plan says EU profiles called from an EU region route only to EU regions, including Ireland (`eu-west-1`) and Spain (`eu-south-2`). Confirm the destinations in this response before the first draft. If any destination is outside the EU, stop and do not deploy with that profile.

## 2. Build the literal index

```powershell
python -m app.ingest.index_fts --root . --out build/index/fts.sqlite3
```

SQLite FTS5, tokenizer `unicode61 remove_diacritics 2`. The index covers both catalogs. Quote verification stays exact after whitespace normalisation.

## 3. Build the Lambda asset

```powershell
python app/infra/scripts/build_lambda.py
```

This installs `app/requirements.txt` for `manylinux2014_x86_64`, Python 3.12, and packs the `app/` package without `web/`, `infra/`, `tests/`, or `eval/`. Output directory: `build/lambda/`.

## 4. Build the web app

```powershell
cd app/web; npm ci; npm run build
```

Output: `app/web/dist/`. The stack also publishes `config.json` (`apiBase`, `region`, `userPoolId`, `clientId`, `cognitoDomain`, `redirectUri`). Local development reads `app/web/public/config.json`.

## 5. Bootstrap and deploy

```powershell
cd app/infra; npm ci; npx cdk bootstrap aws://<account>/eu-west-1; npx cdk deploy
```

Replace `<account>` with the account id from `aws sts get-caller-identity`. Approve the IAM changes only after reading the diff. When the deploy finishes, copy the outputs. Expected names are **a confirmar**; the contract uses these roles:

- web bucket and CloudFront URL
- corpus bucket (`CorpusBucket`) for the FTS index
- cases bucket (`LW_CASES_BUCKET`, SSE-KMS)
- Cognito user pool id and client id
- HTTP API and Step Functions state machine
- DynamoDB table (`LW_TABLE`)

There is no WAF in this stack. See [SECURITY.md](SECURITY.md).

## 6. Upload the index

After the corpus bucket exists:

```powershell
aws s3 cp build/index/fts.sqlite3 s3://<CorpusBucket>/index/fts.sqlite3 --region eu-west-1
```

`<CorpusBucket>` is the stack output. The object key matches `LW_INDEX_S3_KEY` (default `index/fts.sqlite3`). Lambdas download it to `/tmp/fts.sqlite3` on cold start. Re-upload after every index rebuild.

## 7. Create the first Cognito user

Self sign-up is off. Create the user with the admin API, then complete first login in the managed login page, including TOTP MFA.

```powershell
aws cognito-idp admin-create-user --region eu-west-1 --user-pool-id <UserPoolId> --username <email> --user-attributes Name=email,Value=<email> Name=email_verified,Value=true
```

`<UserPoolId>` is a stack output. The pool emails a temporary password (delivery medium is **a confirmar** if the pool is set to suppress email). On first login the user sets a permanent password and enrols a TOTP authenticator. MFA is required, so login is incomplete without that step. Callback URLs are `https://<cloudfront>/` and `http://localhost:5173/`.

## 8. Smoke test

Use a fictional case. Do not paste a real process.

1. Open the CloudFront URL from the stack outputs.
2. Sign in. Confirm the managed login asks for the TOTP code.
3. Confirm the unsigned-draft banner is visible.
4. Call `GET /api/me` through the UI (or the deployed `/api/me` with the ID token). Expect `sub` and `email`.
5. Run a corpus search (`GET /api/search`) so retrieval works without a model call.
6. Optional, and it spends money: create a case with `fictional: true` and a short invented 261/2004 narrative, queue one draft, and confirm status moves `queued` to `running` to `ready` or `failed`. One draft is about 1 to 1.50 USD. Export must fail until every paragraph is accepted, edited, or rejected.

If step 6 fails, follow [RUNBOOK.md](RUNBOOK.md) before launching another draft.

## 9. Teardown

From `app/infra`:

```powershell
npx cdk destroy
```

Destroy removes the stack. Buckets that still hold objects, KMS keys, CloudTrail trails, and the budget alarm may survive, depending on removal policy (**a confirmar** in the CDK). Empty the cases bucket and the corpus bucket first if CloudFormation refuses to delete them. If any real case file was uploaded, follow the incident steps in the runbook before destroy, and keep an audit note that does not copy the file contents.

## 10. Cost

Lean mode is the development setting in `app/CONTRACTS.md`: no WAF, no S3 Vectors in v1, Bedrock only on a user draft or an explicit `--live` eval.

- Budget alarm: 10 USD/month, email `xuyongdong0@gmail.com`.
- One draft: about 1 to 1.50 USD on the public plan (about 80 thousand input tokens and 8 thousand output tokens per pass, three passes). The working figure for this environment is about 1 USD per draft.
- The public plan estimates 20 to 50 USD/month for development infrastructure including WAF. This stack omits WAF, so that range is the plan figure, not a measurement of lean mode.
- The public portal on GitHub Pages stays at 0 USD and never receives case files.

Do not raise the alarm threshold to hide a spike. See the runbook.
