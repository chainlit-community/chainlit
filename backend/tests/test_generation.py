import json

import pytest

import chainlit
from chainlit.generation import (
    BaseGeneration,
    ChatGeneration,
    CompletionGeneration,
    GenerationType,
)

BASE_KEYS: dict = {
    "promptId": None,
    "provider": None,
    "model": None,
    "error": None,
    "settings": {},
    "variables": {},
    "tags": [],
    "metadata": {},
    "tools": None,
    "tokenCount": None,
    "inputTokenCount": None,
    "outputTokenCount": None,
    "ttFirstToken": None,
    "tokenThroughputInSeconds": None,
    "duration": None,
}


def _populated_kwargs():
    return dict(
        id="gen-1",
        prompt_id="p1",
        provider="openai",
        model="gpt-4",
        error="boom",
        settings={"temperature": 0.5},
        variables={"a": "b"},
        tags=["t1"],
        metadata={"m": 1},
        tools=[{"type": "function"}],
        token_count=10,
        input_token_count=4,
        output_token_count=6,
        tt_first_token=0.25,
        token_throughput_in_s=12.5,
        duration=1.5,
    )


def _chat():
    return ChatGeneration(
        **_populated_kwargs(),
        messages=[{"role": "user", "content": "hi"}],
        message_completion={"role": "assistant", "content": "hello"},
    )


def _completion():
    return CompletionGeneration(**_populated_kwargs(), prompt="Say hi", completion="hi")


def test_defaults():
    chat = ChatGeneration()
    assert chat.id is None
    assert chat.settings == {}
    assert chat.tags == []
    assert chat.messages == []
    assert chat.message_completion is None
    assert chat.type == GenerationType.CHAT

    completion = CompletionGeneration()
    assert completion.prompt is None
    assert completion.completion is None
    assert completion.type == GenerationType.COMPLETION


def test_defaults_are_not_shared():
    a, b = ChatGeneration(), ChatGeneration()
    a.settings["x"] = 1
    a.messages.append({"role": "user"})
    assert b.settings == {}
    assert b.messages == []


def test_chat_to_dict_default():
    assert ChatGeneration().to_dict() == {
        **BASE_KEYS,
        "messages": [],
        "messageCompletion": None,
        "type": "CHAT",
    }


def test_completion_to_dict_default():
    assert CompletionGeneration().to_dict() == {
        **BASE_KEYS,
        "prompt": None,
        "completion": None,
        "type": "COMPLETION",
    }


def test_to_dict_includes_id_only_when_set():
    assert "id" not in ChatGeneration().to_dict()
    assert ChatGeneration(id="x").to_dict()["id"] == "x"


def test_chat_to_dict_populated():
    assert _chat().to_dict() == {
        "id": "gen-1",
        "promptId": "p1",
        "provider": "openai",
        "model": "gpt-4",
        "error": "boom",
        "settings": {"temperature": 0.5},
        "variables": {"a": "b"},
        "tags": ["t1"],
        "metadata": {"m": 1},
        "tools": [{"type": "function"}],
        "tokenCount": 10,
        "inputTokenCount": 4,
        "outputTokenCount": 6,
        "ttFirstToken": 0.25,
        "tokenThroughputInSeconds": 12.5,
        "duration": 1.5,
        "messages": [{"role": "user", "content": "hi"}],
        "messageCompletion": {"role": "assistant", "content": "hello"},
        "type": "CHAT",
    }


def test_completion_to_dict_populated():
    d = _completion().to_dict()
    assert d["prompt"] == "Say hi"
    assert d["completion"] == "hi"
    assert d["type"] == "COMPLETION"
    assert d["id"] == "gen-1"
    assert d["tokenThroughputInSeconds"] == 12.5


def test_chat_round_trip():
    chat = _chat()
    restored = ChatGeneration.from_dict(chat.to_dict())
    assert isinstance(restored, ChatGeneration)
    # metadata is not restored by from_dict (matches the original behaviour)
    expected = chat.to_dict()
    expected["metadata"] = {}
    assert restored.to_dict() == expected


def test_completion_round_trip():
    completion = _completion()
    restored = CompletionGeneration.from_dict(completion.to_dict())
    assert isinstance(restored, CompletionGeneration)
    expected = completion.to_dict()
    expected["metadata"] = {}
    assert restored.to_dict() == expected


def test_base_from_dict_dispatch():
    assert isinstance(BaseGeneration.from_dict(_chat().to_dict()), ChatGeneration)
    assert isinstance(
        BaseGeneration.from_dict(_completion().to_dict()), CompletionGeneration
    )


def test_base_from_dict_unknown_type():
    with pytest.raises(ValueError, match="is not a valid GenerationType"):
        BaseGeneration.from_dict({"type": "NOPE"})
    with pytest.raises(ValueError, match="is not a valid GenerationType"):
        BaseGeneration.from_dict({})


def test_str_and_repr_format():
    chat = _chat()
    expected = json.dumps(chat.to_dict(), sort_keys=True, indent=4)
    assert str(chat) == expected
    assert repr(chat) == expected


def test_generation_type_helpers():
    assert str(GenerationType.CHAT) == "CHAT"
    assert repr(GenerationType.COMPLETION) == "GenerationType.COMPLETION"
    assert GenerationType.CHAT.to_json() == "CHAT"


def test_public_api_is_local_classes():
    assert chainlit.ChatGeneration is ChatGeneration
    assert chainlit.CompletionGeneration is CompletionGeneration
    assert chainlit.ChatGeneration.__module__ == "chainlit.generation"
    assert "GenerationMessage" in chainlit.__all__
