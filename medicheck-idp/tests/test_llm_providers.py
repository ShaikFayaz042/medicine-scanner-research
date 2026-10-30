"""Provider plumbing: registry, JSON parsing, and the Bedrock request shape (with a stub client)."""

from __future__ import annotations

import json

import pytest

from idp.models.bedrock import BedrockProvider
from idp.models.llm import LLMError, LLMRequest, create_provider, parse_json_object

REQUEST = LLMRequest(
    system="sys",
    user="classify this",
    json_schema={"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False},
    schema_name="test_schema",
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": "x}"}\n```', {"a": "x}"}),
        ('Here you go: {"a": {"b": [1, 2]}} trailing', {"a": {"b": [1, 2]}}),
    ],
)
def test_parse_json_object_tolerates_fences_and_prose(text, expected):
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("text", ["no json here", '{"a": 1', '[1, 2]'])
def test_parse_json_object_rejects_non_objects(text):
    with pytest.raises(LLMError):
        parse_json_object(text)


def test_registry_builds_providers_by_name_or_path():
    assert create_provider(None) is None and create_provider("none") is None
    provider = create_provider("conftest:FakeProvider", "m1")
    assert (provider.name, provider.model) == ("fake", "m1")
    with pytest.raises(ValueError, match="unknown LLM provider"):
        create_provider("openrouter")


class StubBedrock:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _converse_reply(text, stop="end_turn"):
    return {"output": {"message": {"content": [{"text": text}]}}, "stopReason": stop, "usage": {"inputTokens": 10}}


class FakeClientError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


def test_bedrock_sends_the_schema_as_structured_output():
    client = StubBedrock([_converse_reply('{"a": "ok"}')])

    response = BedrockProvider("in.anthropic.claude-haiku-4-5-20251001-v1:0", client=client).generate_json(REQUEST)

    call = client.calls[0]
    schema = call["outputConfig"]["textFormat"]["structure"]["jsonSchema"]
    assert json.loads(schema["schema"]) == REQUEST.json_schema and schema["name"] == "test_schema"
    assert call["inferenceConfig"]["temperature"] == 0.0 and call["system"] == [{"text": "sys"}]
    assert response.data == {"a": "ok"} and response.schema_enforced


def test_bedrock_falls_back_to_prompting_when_structured_output_is_unsupported():
    client = StubBedrock([
        FakeClientError("ValidationException", "Structured outputs are not supported for this inference profile"),
        _converse_reply('```json\n{"a": "ok"}\n```'),
        _converse_reply('{"a": "again"}'),
    ])
    provider = BedrockProvider("in.anthropic.claude-haiku-4-5-20251001-v1:0", client=client)

    first = provider.generate_json(REQUEST)
    second = provider.generate_json(REQUEST)

    assert "outputConfig" not in client.calls[1] and "JSON Schema" in client.calls[1]["messages"][0]["content"][0]["text"]
    assert "outputConfig" not in client.calls[2]  # remembered for the rest of the process
    assert (first.data, second.data, first.schema_enforced) == ({"a": "ok"}, {"a": "again"}, False)


def test_bedrock_reports_truncated_and_failed_calls():
    with pytest.raises(LLMError, match="max token"):
        BedrockProvider("m", client=StubBedrock([_converse_reply('{"a": ', stop="max_tokens")])).generate_json(REQUEST)
    with pytest.raises(LLMError, match="throttled"):
        BedrockProvider("m", client=StubBedrock([FakeClientError("ThrottlingException", "throttled")])).generate_json(REQUEST)


def test_bedrock_needs_a_model_id():
    with pytest.raises(ValueError, match="IDP_LLM_MODEL"):
        BedrockProvider(None, client=StubBedrock([]))
