"""Amazon Bedrock provider (Converse API).

Authentication comes from the ECS task role (or the usual AWS credential chain locally), so no key is
stored. `model` is a model or inference-profile ID, e.g. the India profile
"in.anthropic.claude-haiku-4-5-20251001-v1:0".

Structured outputs (outputConfig.textFormat) are used when enabled. Some model/profile combinations do
not support them (AWS documents Claude Haiku 4.5 through the India `in.anthropic` profile as one), so a
ValidationException about the output format switches this provider to prompt-and-parse mode for the
rest of the process.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from idp.models.llm import LLMError, LLMRequest, LLMResponse, parse_json_object, schema_instruction

log = logging.getLogger(__name__)


class BedrockProvider:
    name = "bedrock"

    def __init__(
        self,
        model: Optional[str],
        region: Optional[str] = None,
        structured_output: bool = True,
        temperature: float = 0.0,
        timeout_seconds: int = 120,
        max_attempts: int = 3,
        client: Any = None,
    ) -> None:
        if not model:
            raise ValueError("BedrockProvider needs a model or inference-profile ID (IDP_LLM_MODEL)")
        self.model = model
        self.temperature = temperature
        self._structured = structured_output
        if client is None:
            import boto3
            from botocore.config import Config

            # The first call with a new schema compiles a grammar (up to ~90 s, per AWS docs).
            client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(read_timeout=timeout_seconds, retries={"max_attempts": max_attempts, "mode": "standard"}),
            )
        self._client = client

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        user = request.user if self._structured else request.user + schema_instruction(request.json_schema)
        kwargs: dict = {
            "modelId": self.model,
            "system": [{"text": request.system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"maxTokens": request.max_output_tokens, "temperature": self.temperature},
        }
        if self._structured:
            kwargs["outputConfig"] = {
                "textFormat": {
                    "type": "json_schema",
                    "structure": {"jsonSchema": {"schema": json.dumps(request.json_schema), "name": request.schema_name}},
                }
            }
        try:
            response = self._client.converse(**kwargs)
        except Exception as error:  # botocore ClientError, timeouts
            code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
            message = str(error).lower()
            if self._structured and code == "ValidationException" and any(w in message for w in ("output", "structured", "schema", "format")):
                log.warning("Bedrock model %s rejected structured outputs; using prompt-and-parse instead: %s", self.model, error)
                self._structured = False
                return self.generate_json(request)
            raise LLMError(f"Bedrock call failed: {error}") from error

        if response.get("stopReason") == "max_tokens":
            raise LLMError("the reply hit the max token limit before the JSON object was complete")
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(block.get("text", "") for block in blocks)
        return LLMResponse(
            data=parse_json_object(text),
            raw_text=text,
            provider=self.name,
            model=self.model,
            schema_enforced=self._structured,
            usage=dict(response.get("usage") or {}),
        )
