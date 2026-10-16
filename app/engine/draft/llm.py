"""Bedrock JSON completion for Minutas drafts.

The model is forced through a single tool so the reply is a JSON object.
No network call happens until ``complete_json`` builds the client.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import boto3
from botocore.config import Config


DEFAULT_MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_REGION = "eu-west-1"
TOOL_NAME = "emit"
TOOL_DESCRIPTION = "Emitir o objeto JSON deste passo, sem texto livre."


class LLM(Protocol):
    """Structured-output model used by the drafting pipeline."""

    model_id: str
    usage: dict[str, int]

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = 8000,
    ) -> dict[str, Any]:
        """Return one JSON object matching ``schema``."""


def parse_converse_output(response: dict[str, Any]) -> dict[str, Any]:
    """Pull the ``emit`` tool input out of a Converse response."""

    message = (response.get("output") or {}).get("message") or {}
    content = message.get("content") or []
    for block in content:
        if not isinstance(block, dict):
            continue
        tool = block.get("toolUse")
        if not isinstance(tool, dict):
            continue
        if tool.get("name") != TOOL_NAME:
            continue
        raw = tool.get("input")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict):
            return raw
        raise RuntimeError("A ferramenta emit não devolveu um objeto JSON.")
    raise RuntimeError("A resposta do Bedrock não contém a ferramenta emit.")


class BedrockLLM:
    """Amazon Bedrock Converse client with a forced ``emit`` tool.

    ``model_id`` falls back to ``LW_MODEL_ID`` and then to the EU Sonnet
    inference profile. ``region`` falls back to ``LW_REGION`` and then to
    ``eu-west-1``. Token counters accumulate across calls.
    """

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self.model_id = model_id or os.environ.get("LW_MODEL_ID") or DEFAULT_MODEL_ID
        self.region = region or os.environ.get("LW_REGION") or DEFAULT_REGION
        self.usage = {"inputTokens": 0, "outputTokens": 0}
        self._client: Any = None

    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    retries={"mode": "adaptive", "max_attempts": 5},
                    read_timeout=300,
                ),
            )
        return self._client

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        max_tokens: int = 8000,
    ) -> dict[str, Any]:
        request = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user}],
                }
            ],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": 0.0,
            },
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": TOOL_NAME,
                            "description": TOOL_DESCRIPTION,
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": TOOL_NAME}},
            },
        }
        response = self.client().converse(**request)
        usage = response.get("usage") or {}
        self.usage["inputTokens"] += int(usage.get("inputTokens") or 0)
        self.usage["outputTokens"] += int(usage.get("outputTokens") or 0)
        return parse_converse_output(response)
