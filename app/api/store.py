"""DynamoDB, S3, and Step Functions access for Minutas.

`MemoryStore` is the in-memory fake used by offline tests. `AwsStore` talks to
AWS and is constructed lazily from the environment on first use.

PDF uploads are presigned PUTs (Content-Type `application/pdf`, 10 minutes).
S3 presigned PUT URLs cannot carry a `content-length-range` condition. The
15 MB ceiling is therefore enforced by the draft worker before extraction
(`MAX_PDF_BYTES` in `app.api.common`). The cases bucket is expected to apply
its default SSE-KMS encryption; these calls do not send a KMS key id.
"""

from __future__ import annotations

import copy
import json
import os
from decimal import Decimal
from typing import Any

_NOT_FOUND = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchBucket"})


def _is_not_found(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = str((response.get("Error") or {}).get("Code", ""))
    return code in _NOT_FOUND


def _clean(value: Any) -> Any:
    """Drop None so DynamoDB writes stay valid. Leaves empty strings."""
    if isinstance(value, dict):
        return {key: _clean(inner) for key, inner in value.items() if inner is not None}
    if isinstance(value, list):
        return [_clean(inner) for inner in value]
    if isinstance(value, tuple):
        return [_clean(inner) for inner in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: _from_dynamo(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(inner) for inner in value]
    return value


class MemoryStore:
    """Process-local stand-in for the single table, the cases bucket, and SFN."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict] = {}
        self._objects: dict[str, dict] = {}
        self.presign_puts: list[dict] = []
        self.presign_gets: list[dict] = []
        self.executions: list[dict] = []
        self.start_error: BaseException | None = None

    def put_item(self, item: dict) -> None:
        stored = copy.deepcopy(_clean(item))
        self._items[(stored["PK"], stored["SK"])] = stored

    def put_items(self, items: list[dict]) -> None:
        for item in items:
            self.put_item(item)

    def get_item(self, pk: str, sk: str) -> dict | None:
        found = self._items.get((pk, sk))
        if found is None:
            return None
        return copy.deepcopy(found)

    def query(self, pk: str, sk_prefix: str = "") -> list[dict]:
        rows = [
            copy.deepcopy(item)
            for (item_pk, item_sk), item in self._items.items()
            if item_pk == pk and item_sk.startswith(sk_prefix)
        ]
        rows.sort(key=lambda item: item["SK"])
        return rows

    def put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        self._objects[key] = {"body": bytes(body), "contentType": content_type}

    def get_bytes(self, key: str) -> bytes | None:
        found = self._objects.get(key)
        if found is None:
            return None
        return bytes(found["body"])

    def head(self, key: str) -> dict | None:
        found = self._objects.get(key)
        if found is None:
            return None
        return {"contentLength": len(found["body"]), "contentType": found["contentType"]}

    def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        self.presign_puts.append(
            {"key": key, "content_type": content_type, "expires_in": expires_in}
        )
        return f"https://s3.example/{key}?X-Amz-Expires={expires_in}&Content-Type={content_type}"

    def presign_get(self, key: str, expires_in: int) -> str:
        self.presign_gets.append({"key": key, "expires_in": expires_in})
        return f"https://s3.example/{key}?X-Amz-Expires={expires_in}"

    def start_execution(self, state_machine_arn: str, payload: dict) -> dict:
        if self.start_error is not None:
            raise self.start_error
        record = {"stateMachineArn": state_machine_arn, "input": copy.deepcopy(payload)}
        self.executions.append(record)
        draft_id = str(payload.get("draftId") or "draft")
        return {"executionArn": f"arn:aws:states:eu-west-1:000000000000:execution:minutas:{draft_id}"}


class AwsStore:
    """boto3-backed repository. Clients are passed in so tests can stub them."""

    def __init__(self, *, table: Any, s3: Any, sfn: Any, bucket: str) -> None:
        self.table = table
        self.s3 = s3
        self.sfn = sfn
        self.bucket = bucket

    @classmethod
    def from_env(cls) -> "AwsStore":
        import boto3

        region = os.environ.get("LW_REGION", "eu-west-1")
        table_name = os.environ["LW_TABLE"]
        bucket = os.environ["LW_CASES_BUCKET"]
        dynamodb = boto3.resource("dynamodb", region_name=region)
        s3 = boto3.client("s3", region_name=region)
        sfn = boto3.client("stepfunctions", region_name=region)
        return cls(table=dynamodb.Table(table_name), s3=s3, sfn=sfn, bucket=bucket)

    def put_item(self, item: dict) -> None:
        self.table.put_item(Item=_clean(item))

    def put_items(self, items: list[dict]) -> None:
        with self.table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=_clean(item))

    def get_item(self, pk: str, sk: str) -> dict | None:
        response = self.table.get_item(Key={"PK": pk, "SK": sk})
        item = response.get("Item")
        if not item:
            return None
        return _from_dynamo(item)

    def query(self, pk: str, sk_prefix: str = "") -> list[dict]:
        from boto3.dynamodb.conditions import Key

        if sk_prefix:
            expression = Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix)
        else:
            expression = Key("PK").eq(pk)
        kwargs: dict[str, Any] = {"KeyConditionExpression": expression}
        rows: list[dict] = []
        while True:
            response = self.table.query(**kwargs)
            rows.extend(_from_dynamo(item) for item in response.get("Items", []))
            last = response.get("LastEvaluatedKey")
            if not last:
                return rows
            kwargs["ExclusiveStartKey"] = last

    def put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes | None:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        return response["Body"].read()

    def head(self, key: str) -> dict | None:
        try:
            response = self.s3.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        return {
            "contentLength": int(response.get("ContentLength") or 0),
            "contentType": response.get("ContentType") or "",
        }

    def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        return self.s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )

    def presign_get(self, key: str, expires_in: int) -> str:
        return self.s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def start_execution(self, state_machine_arn: str, payload: dict) -> dict:
        from app.api.common import new_rand4

        draft_id = str(payload.get("draftId") or "draft")
        return self.sfn.start_execution(
            stateMachineArn=state_machine_arn,
            name=f"{draft_id}-{new_rand4()}",
            input=json.dumps(payload),
        )


_store: MemoryStore | AwsStore | None = None


def get_store() -> MemoryStore | AwsStore:
    global _store
    if _store is None:
        _store = AwsStore.from_env()
    return _store


def set_store(store: MemoryStore | AwsStore | None) -> None:
    global _store
    _store = store
