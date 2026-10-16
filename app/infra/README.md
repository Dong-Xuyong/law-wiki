# Minutas infra

Dev stack `LwMinutasDev` in `eu-west-1`. Fictional and published cases only. No WAF.

## Build the Lambda asset

From the repo root (no Docker). Re-run this after `app/` code changes, before synth or deploy:

```powershell
C:\Users\Dong\miniconda3\python.exe app\infra\scripts\build_lambda.py
```

The script wipes `build/lambda`, installs `app/requirements.txt` for Linux x86_64 / CPython 3.12, and copies the `app` package without `web`, `infra`, `tests`, or `eval`. `boto3` is not included.

## Build the web app

When `app/web` exists:

```powershell
Set-Location app\web
npm install
npm run build
```

Synth deploys `app/web/dist` if that folder is non-empty. Otherwise it deploys a placeholder `index.html` so synth still succeeds. `config.json` is generated at deploy time.

## Synth

```powershell
Set-Location app\infra
npm install
npx tsc --noEmit
npx cdk synth
```

Set `CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION=eu-west-1` if the CLI cannot see the account. Do not print credentials.

## Deploy (supervisor)

Bootstrap once per account and region if `CDKToolkit` is not already in `eu-west-1`. Then deploy:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
$env:CDK_DEFAULT_ACCOUNT = "516116818375"
$env:CDK_DEFAULT_REGION = "eu-west-1"
Set-Location app\infra
npx cdk bootstrap aws://516116818375/eu-west-1
npx cdk deploy LwMinutasDev
```

Before the app is usable: confirm the budget email, create the judge in Cognito (self sign-up is off) and enrol TOTP, upload `index/fts.sqlite3` to the corpus bucket, and allow the EU Anthropic inference profile in Bedrock. Rebuild the Lambda asset after the API and engine land, then deploy again if the first asset was incomplete.
