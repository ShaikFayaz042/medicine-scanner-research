"""Google Gemini provider (google-genai SDK), the alternative to Bedrock.

Needs `pip install google-genai` and GEMINI_API_KEY. Uses `response_json_schema` when the installed SDK
supports it, otherwise JSON mode plus the schema in the prompt. Not exercised against the live API in
this repository's tests (they use a fake provider).
"""

from __future__ import annotations

from typing import Any, Optional

from idp.models.llm import LLMError, LLMRequest, LLMResponse, parse_json_object, schema_instruction


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        model: Optional[str],
        api_key: Optional[str] = None,
        temperature: float = 0.0,
        client: Any = None,
        **_ignored: Any,
    ) -> None:
        if not model:
            raise ValueError("GeminiProvider needs a model name (IDP_LLM_MODEL)")
        self.model = model
        self.temperature = temperature
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self._client = client

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        from google.genai import types

        enforce = "response_json_schema" in getattr(types.GenerateContentConfig, "model_fields", {})
        options = dict(
            system_instruction=request.system,
            response_mime_type="application/json",
            temperature=self.temperature,
            max_output_tokens=request.max_output_tokens,
        )
        if enforce:
            options["response_json_schema"] = request.json_schema
        user = request.user if enforce else request.user + schema_instruction(request.json_schema)
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=user, config=types.GenerateContentConfig(**options)
            )
        except Exception as error:
            raise LLMError(f"Gemini call failed: {error}") from error
        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            data=parse_json_object(text),
            raw_text=text,
            provider=self.name,
            model=self.model,
            schema_enforced=enforce,
            usage=usage.model_dump() if hasattr(usage, "model_dump") else {},
        )
