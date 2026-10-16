# Minutas runbook (development)

Operate the `eu-west-1` development stack. It may contain fictional cases and published decisions. It must not contain real case files. Commands assume the AWS CLI session from [DEPLOY.md](DEPLOY.md) and region `eu-west-1`.

Resource names below that are not fixed in `app/CONTRACTS.md` are **a confirmar** until the CDK outputs exist.

## Operating checks

Run these after a deploy and after an index upload.

| Check | What good looks like |
|---|---|
| Identity | `aws sts get-caller-identity` is the project account, not root |
| Inference profile | `aws bedrock get-inference-profile --region eu-west-1 --inference-profile-identifier eu.anthropic.claude-sonnet-4-5-20250929-v1:0` lists only EU destinations |
| Index object | `s3://<CorpusBucket>/index/fts.sqlite3` exists and its size matches `build/index/fts.sqlite3` |
| API auth | `GET /api/me` with a valid ID token returns `sub` and `email`; the same call without a token is rejected |
| Owner scope | A token for user A does not read user B's case (response 404) |
| Fictional gate | `POST /api/cases` without `fictional: true` returns 400 `fictional_required` |
| Export gate | `POST /api/drafts/{id}/export` returns 409 `unreviewed` while any paragraph is pending |
| Budget | The 10 USD/month alarm is still enabled and still notifies `xuyongdong0@gmail.com` |
| Sign-up | The Cognito user pool has self sign-up disabled and MFA required (TOTP) |

Search (`GET /api/search`) is the cheap retrieval check. Generating a draft is not a routine health check.

## Where logs are

Three places, and none of them should contain case text.

1. **CloudWatch Logs** for the two Lambdas (`api`, 30 seconds, and `draft_worker`, up to 900 seconds). Log group names follow the function names and are **a confirmar**. Use them for timeouts, import errors, and Bedrock error codes.
2. **CloudTrail** for management and API activity in the account. Who changed the stack, who created a user, who deleted an object.
3. **DynamoDB audit items** in `LW_TABLE`. Partition key `AUDIT#{draftId}`, sort key `{iso8601}#{rand4}`. Fields: `actor`, `action` (`generate`, `accept`, `edit`, `reject`, `export`), optional `paragraphId`, `modelId`, `promptSha256`, `sourceIds`, `textSha256`. The audit stores hashes and source ids.

Step Functions execution history shows whether the worker was started and how it ended. The execution input in the contract is `{"caseId", "draftId"}` only.

If a log line contains petition text, a party name, or a process number from an uploaded file, treat it as an incident: delete or redact that log stream if the service allows it, record an audit note, and fix the logger before the next deploy.

## Failed draft triage

A failed draft has `status: failed` and an `error` string on the draft meta item (`PK = DRAFT#{draftId}`, `SK = META`).

1. Read `error`, the worker CloudWatch stream for that request id, and the Step Functions execution. Look for timeout (900 seconds), a missing index in `/tmp/fts.sqlite3`, a Bedrock access or throttling error, or a validation error after the repair loop (`max_repairs` is 2).
2. Do not copy the case text into a ticket, a chat, or a log statement. Identify the draft by `draftId` and the case by `caseId`.
3. If the index is missing or stale, rebuild it, upload it to `index/fts.sqlite3`, and start a **new** draft. Do not edit a failed packet in place.
4. If Bedrock rejected the model id, re-check the inference profile in [DEPLOY.md](DEPLOY.md). Do not point `LW_MODEL_ID` at a non-`eu.` profile.
5. One retry is enough to see if the failure is transient. Further retries cost about 1 USD each. Stop after one retry if the error is unchanged.

`errors` inside a draft result are validation failures. An empty `errors` list means `validate_packet` passed. A failed status means the worker did not reach a valid packet.

## Rotating users

Self sign-up stays off. Add a person with `admin-create-user` as in the deploy guide, then require TOTP on first login.

To remove access:

```powershell
aws cognito-idp admin-disable-user --region eu-west-1 --user-pool-id <UserPoolId> --username <email>
```

Disabling the user blocks new tokens. Existing tokens last until they expire (**a confirmar** against the pool's token validity). For a suspected leak, disable the user and rotate that person's cases only by deleting them under the incident steps if the account itself is untrusted. There is no shared case list: items are keyed by `USER#{sub}`.

Do not create a user without MFA, and do not turn self sign-up on for a demo.

## Incident: real data uploaded by mistake

Stop. Do not open the file in a ticket. Do not generate a draft from it.

1. Disable the Cognito user who uploaded it if the upload was unauthorised or the account is shared.
2. Delete the S3 objects for that case in the cases bucket: `cases/{caseId}/input.pdf`, `cases/{caseId}/input.txt`, `drafts/{draftId}/packet.json`, and `exports/{draftId}.docx`. Delete every draft and export for that case. Confirm with `aws s3 ls` that the prefixes are gone.
3. Delete the DynamoDB items for that case and its drafts: `USER#{sub}` / `CASE#{caseId}`, `CASE#{caseId}` / `DRAFT#{draftId}`, `DRAFT#{draftId}` / `META`, and `DRAFT#{draftId}` / `PARA#*`. Delete paragraph items because they contain draft text.
4. Write an audit note that does not reproduce the content. Record date, `caseId`, `draftId` if any, who deleted the objects, and that a non-fictional upload was removed. Keep that note in the operator log for this environment. If an `AUDIT#` item already stores only hashes, leave the hash record and add the deletion note beside it. If any item stored the raw text, delete that item after the note exists.
5. Check CloudWatch for the same window and remove log events that captured the body, if any.
6. Tell Dong. Do not put party names or file text in the message. The CSM validation path is unchanged: this environment is still not approved for real proceedings.

The corpus bucket holds published law and the FTS index. Do not delete it as part of a case-upload incident.

## Cost spike

The alarm is 10 USD/month to `xuyongdong0@gmail.com`.

1. Stop draft generation and do not run `python -m app.eval run --live`.
2. In Cost Explorer, filter the project account to `eu-west-1` and to Amazon Bedrock. A single draft is about 1 to 1.50 USD, so a handful of drafts can trip a 10 USD alarm. Confirm the spike is drafts and not a runaway loop.
3. Check Step Functions executions and `draft_worker` invocations for retries. A failed draft that is retried in a loop is the usual spike.
4. Leave the alarm at 10 USD. Raising it is a decision for Dong.
5. If spend continues with nobody generating drafts, disable the worker's event source by stopping new `POST /api/cases/{id}/drafts` traffic (disable the Cognito users) and inspect Bedrock CloudWatch metrics before the next deploy.

WAF is absent on purpose in lean mode. A traffic flood against CloudFront can still create a small cost. The alarm is the backstop. See [SECURITY.md](SECURITY.md).
