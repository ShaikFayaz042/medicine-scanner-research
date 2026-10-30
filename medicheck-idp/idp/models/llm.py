"""Provider-neutral LLM interface for JSON-returning calls.

Stages ask for "a JSON object for this system prompt, user prompt and JSON Schema". Providers decide
how: schema-constrained decoding when the model/endpoint supports it, otherwise the schema is added to
the prompt and the reply is parsed. Callers must still validate the result; nothing here trusts it.

Choosing a provider is configuration only (config/settings.py):
    IDP_LLM_PROVIDER = none | bedrock | gemini | <package.module:ClassName>
A new provider is a class with `name`, `model` and `generate_json(request) -> LLMResponse`.
"""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, runtime_checkable

PROVIDERS = {
    "bedrock": "idp.models.bedrock:BedrockProvider",
    "gemini": "idp.models.gemini:GeminiProvider",
}


class LLMError(RuntimeError):
    """The provider failed or returned something that is not a JSON object."""


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    json_schema: Dict[str, Any]
    schema_name: str
    max_output_tokens: int = 1024


@dataclass(frozen=True)
class LLMResponse:
    data: Dict[str, Any]
    raw_text: str
    provider: str
    model: str
    schema_enforced: bool
    usage: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, request: LLMRequest) -> LLMResponse: ...


def create_provider(name: Optional[str], model: Optional[str] = None, **options: Any) -> Optional[LLMProvider]:
    """Build the configured provider; None (or "none") disables the LLM fallback."""
    if not name or name.lower() == "none":
        return None
    target = PROVIDERS.get(name.lower(), name)
    if ":" not in target:
        raise ValueError(f"unknown LLM provider {name!r}; use one of {sorted(PROVIDERS)} or 'package.module:Class'")
    module_name, class_name = target.split(":", 1)
    provider_class = getattr(importlib.import_module(module_name), class_name)
    return provider_class(model=model, **options)


def schema_instruction(schema: Dict[str, Any]) -> str:
    """Appended to the prompt when the provider cannot enforce the schema itself."""
    return (
        "\n\nReturn ONLY one JSON object, with no Markdown fences and no commentary, that validates against "
        "this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
    )


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_object(text: str) -> Dict[str, Any]:
    """The first complete JSON object in `text` (tolerates code fences and leading prose)."""
    cleaned = _FENCE.sub("", text or "").strip()
    start = cleaned.find("{")
    if start < 0:
        raise LLMError("no JSON object in the model reply")
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(cleaned[start:index + 1])
                except json.JSONDecodeError as error:
                    raise LLMError(f"invalid JSON in the model reply: {error}") from error
                if not isinstance(value, dict):
                    raise LLMError("the model reply is not a JSON object")
                return value
    raise LLMError("unterminated JSON object in the model reply")
