"""Offline tests for repository helpers and the boto3 adapter."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from app.api.common import new_public_id, new_rand4, now_iso
from app.api.store import AwsStore, MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_ids_timestamps_and_copy_isolation(self):
        self.assertRegex(new_public_id("c_"), r"^c_[a-z0-9]{10}$")
        self.assertRegex(new_public_id("d_"), r"^d_[a-z0-9]{10}$")
        self.assertRegex(new_rand4(), r"^[a-z0-9]{4}$")
        self.assertRegex(now_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$")
        store = MemoryStore()
        store.put_item({"PK": "USER#a", "SK": "CASE#c_aaaaaaaaaa", "title": "t", "skip": None})
        loaded = store.get_item("USER#a", "CASE#c_aaaaaaaaaa")
        self.assertNotIn("skip", loaded)
        loaded["title"] = "changed"
        self.assertEqual(store.get_item("USER#a", "CASE#c_aaaaaaaaaa")["title"], "t")
        self.assertEqual(store.query("USER#a", "CASE#")[0]["title"], "t")
        self.assertIsNone(store.get_bytes("missing"))
        store.put_bytes("cases/c_aaaaaaaaaa/input.txt", "olá".encode("utf-8"), "text/plain")
        self.assertEqual(store.head("cases/c_aaaaaaaaaa/input.txt")["contentLength"], len("olá".encode("utf-8")))


class AwsStoreTests(unittest.TestCase):
    def _store(self):
        return AwsStore(table=MagicMock(), s3=MagicMock(), sfn=MagicMock(), bucket="cases-bucket")

    def test_query_paginates_and_converts_decimals(self):
        store = self._store()
        store.table.query.side_effect = [
            {
                "Items": [{"PK": "USER#a", "SK": "CASE#c_aaaaaaaaaa", "n": Decimal("2")}],
                "LastEvaluatedKey": {"PK": "USER#a", "SK": "CASE#c_aaaaaaaaaa"},
            },
            {"Items": [{"PK": "USER#a", "SK": "CASE#c_bbbbbbbbbb", "n": Decimal("2.5")}]},
        ]
        rows = store.query("USER#a", "CASE#")
        self.assertEqual(rows[0]["n"], 2)
        self.assertEqual(rows[1]["n"], 2.5)
        self.assertIn("ExclusiveStartKey", store.table.query.call_args_list[1].kwargs)

    def test_missing_objects_and_presign_and_execution(self):
        store = self._store()
        store.table.get_item.return_value = {}
        self.assertIsNone(store.get_item("USER#a", "CASE#c_aaaaaaaaaa"))

        store.s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "no"}},
            "GetObject",
        )
        self.assertIsNone(store.get_bytes("missing"))
        store.s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "no"}},
            "HeadObject",
        )
        self.assertIsNone(store.head("missing"))

        store.s3.generate_presigned_url.return_value = "https://signed"
        url = store.presign_put("cases/c_aaaaaaaaaa/input.pdf", "application/pdf", 600)
        self.assertEqual(url, "https://signed")
        kwargs = store.s3.generate_presigned_url.call_args.kwargs
        self.assertEqual(kwargs["ClientMethod"], "put_object")
        self.assertEqual(kwargs["ExpiresIn"], 600)
        self.assertEqual(kwargs["Params"]["Bucket"], "cases-bucket")
        self.assertEqual(kwargs["Params"]["Key"], "cases/c_aaaaaaaaaa/input.pdf")
        self.assertEqual(kwargs["Params"]["ContentType"], "application/pdf")

        store.presign_get("exports/d_bbbbbbbbbb.docx", 600)
        get_kwargs = store.s3.generate_presigned_url.call_args.kwargs
        self.assertEqual(get_kwargs["ClientMethod"], "get_object")
        self.assertEqual(get_kwargs["ExpiresIn"], 600)
        self.assertEqual(get_kwargs["Params"]["Key"], "exports/d_bbbbbbbbbb.docx")

        store.put_bytes("cases/c_aaaaaaaaaa/input.txt", b"ola", "text/plain")
        put = store.s3.put_object.call_args.kwargs
        self.assertEqual(put["Bucket"], "cases-bucket")
        self.assertEqual(put["Body"], b"ola")
        self.assertEqual(put["ContentType"], "text/plain")

        batch = MagicMock()
        store.table.batch_writer.return_value.__enter__.return_value = batch
        store.put_items([{"PK": "A", "SK": "B", "n": 1, "gone": None}])
        written = batch.put_item.call_args.kwargs["Item"]
        self.assertEqual(written["n"], 1)
        self.assertNotIn("gone", written)

        store.sfn.start_execution.return_value = {"executionArn": "arn:exec"}
        response = store.start_execution(
            "arn:aws:states:eu-west-1:123:stateMachine:minutas",
            {"caseId": "c_aaaaaaaaaa", "draftId": "d_bbbbbbbbbb"},
        )
        self.assertEqual(response["executionArn"], "arn:exec")
        started = store.sfn.start_execution.call_args.kwargs
        self.assertEqual(started["stateMachineArn"], "arn:aws:states:eu-west-1:123:stateMachine:minutas")
        self.assertEqual(
            json.loads(started["input"]),
            {"caseId": "c_aaaaaaaaaa", "draftId": "d_bbbbbbbbbb"},
        )
        self.assertRegex(started["name"], r"^d_bbbbbbbbbb-[a-z0-9]{4}$")


if __name__ == "__main__":
    unittest.main()
