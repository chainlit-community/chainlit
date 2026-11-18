"""Tests for the vendored Mistral AI instrumentation behind `cl.instrument_mistralai()`.

`mistralai` is not a test dependency, so stub `mistralai.chat.Chat` and
`mistralai.fim.Fim` classes are injected into `sys.modules`. Their return values
mimic the mistralai 1.x response models (`ChatCompletionResponse`,
`FIMCompletionResponse`, `CompletionEvent`) as far as the instrumentation reads
them.
"""

import sys
import types
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pydantic import BaseModel

from chainlit._instrumentation import mistralai as mistral_instrumentation
from chainlit.generation import ChatGeneration, CompletionGeneration

MESSAGES = [{"role": "user", "content": "Say hello"}]
RESPONSE_MODEL = "mistral-small-2409"


class FunctionCall(BaseModel):
    name: Optional[str] = None
    arguments: Optional[str] = None


class ToolCall(BaseModel):
    id: Optional[str] = None
    function: FunctionCall


class AssistantMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class Choice(BaseModel):
    index: int = 0
    message: AssistantMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 7
    completion_tokens: int = 3
    total_tokens: int = 10


class CompletionResponse(BaseModel):
    id: str = "cmpl-1"
    model: str = RESPONSE_MODEL
    choices: List[Choice]
    usage: Usage = Usage()


class DeltaMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: Optional[str] = None


class CompletionChunk(BaseModel):
    id: str = "cmpl-1"
    model: str = RESPONSE_MODEL
    choices: List[StreamChoice]


class CompletionEvent(BaseModel):
    data: CompletionChunk


def _event(**delta) -> CompletionEvent:
    return CompletionEvent(
        data=CompletionChunk(choices=[StreamChoice(delta=DeltaMessage(**delta))])
    )


TEXT_EVENTS = [
    _event(role="assistant", content=""),
    _event(content="Hel"),
    _event(content="lo!"),
]

TOOL_CALL_EVENTS = [
    _event(
        tool_calls=[
            ToolCall(
                id="call_1", function=FunctionCall(name="get_weather", arguments="")
            )
        ]
    ),
    _event(tool_calls=[ToolCall(function=FunctionCall(arguments='{"city":'))]),
    _event(tool_calls=[ToolCall(function=FunctionCall(arguments='"Paris"}'))]),
]


def _response(content: str, **message) -> CompletionResponse:
    return CompletionResponse(
        choices=[Choice(message=AssistantMessage(content=content, **message))]
    )


class EventStream:
    """Mimics mistralai.utils.eventstreaming.EventStream: an iterator, not a generator."""

    def __init__(self, events):
        self._events = iter(events)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._events)


class EventStreamAsync:
    def __init__(self, events):
        self._events = iter(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeSDK:
    """Shared state for the stub Chat / Fim resources."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.events: List[CompletionEvent] = TEXT_EVENTS
        self.event_stream = False

    def make_resource(self, content: str):
        sdk = self

        class Resource:
            def complete(self, **kwargs):
                sdk.calls.append(kwargs)
                return _response(content)

            def stream(self, **kwargs):
                sdk.calls.append(kwargs)
                if sdk.event_stream:
                    return EventStream(sdk.events)
                return (event for event in sdk.events)

            async def complete_async(self, **kwargs):
                sdk.calls.append(kwargs)
                return _response(content)

            async def stream_async(self, **kwargs):
                sdk.calls.append(kwargs)
                if sdk.event_stream:
                    return EventStreamAsync(sdk.events)

                async def generate():
                    for event in sdk.events:
                        yield event

                return generate()

        return Resource


@pytest.fixture
def sdk(monkeypatch) -> FakeSDK:
    fake = FakeSDK()
    chat_module = types.ModuleType("mistralai.chat")
    chat_module.Chat = fake.make_resource("Hello!")  # type: ignore[attr-defined]
    fim_module = types.ModuleType("mistralai.fim")
    fim_module.Fim = fake.make_resource("return 42")  # type: ignore[attr-defined]
    eventstreaming = types.ModuleType("mistralai.utils.eventstreaming")
    eventstreaming.EventStream = EventStream  # type: ignore[attr-defined]
    eventstreaming.EventStreamAsync = EventStreamAsync  # type: ignore[attr-defined]

    for name, module in {
        "mistralai": types.ModuleType("mistralai"),
        "mistralai.chat": chat_module,
        "mistralai.fim": fim_module,
        "mistralai.utils": types.ModuleType("mistralai.utils"),
        "mistralai.utils.eventstreaming": eventstreaming,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    fake.chat = chat_module.Chat()  # type: ignore[attr-defined]
    fake.fim = fim_module.Fim()  # type: ignore[attr-defined]
    monkeypatch.setattr(mistral_instrumentation, "is_mistralai_instrumented", False)
    return fake


@pytest.fixture
def generations(sdk) -> List[Tuple[Any, Dict[str, float]]]:
    captured: List[Tuple[Any, Dict[str, float]]] = []
    mistral_instrumentation.instrument_mistralai(
        lambda generation, timing: captured.append((generation, timing))
    )
    return captured


def _assert_timing(generation, timing):
    assert set(timing) == {"start", "end"}
    assert timing["start"] <= timing["end"]
    assert generation.duration is not None


def _assert_chat(generation, settings):
    assert isinstance(generation, ChatGeneration)
    assert generation.provider == "mistralai"
    assert generation.messages == MESSAGES
    assert generation.settings == settings


def test_chat_complete(generations, sdk):
    result = sdk.chat.complete(
        model="mistral-small-latest", messages=MESSAGES, temperature=0.1
    )

    assert result.choices[0].message.content == "Hello!"
    generation, timing = generations[0]
    _assert_chat(generation, {"model": RESPONSE_MODEL, "temperature": 0.1})
    assert generation.model == RESPONSE_MODEL
    assert generation.message_completion == {
        "role": "assistant",
        "content": "Hello!",
        "tool_calls": None,
    }
    assert generation.input_token_count == 7
    assert generation.output_token_count == 3
    assert generation.token_count == 10
    _assert_timing(generation, timing)


async def test_chat_complete_async(generations, sdk):
    await sdk.chat.complete_async(model="mistral-small-latest", messages=MESSAGES)

    generation, timing = generations[0]
    _assert_chat(generation, {"model": RESPONSE_MODEL})
    assert generation.message_completion["content"] == "Hello!"
    assert generation.token_count == 10
    _assert_timing(generation, timing)


@pytest.mark.parametrize("event_stream", [False, True])
def test_chat_stream(generations, sdk, event_stream):
    sdk.event_stream = event_stream

    stream = sdk.chat.stream(model="mistral-small-latest", messages=MESSAGES)
    assert generations == []
    events = list(stream)

    assert events == TEXT_EVENTS
    generation, timing = generations[0]
    # Stream events carry the model on `event.data`, which the instrumentation
    # (like the original) does not pick up: the requested model is kept.
    _assert_chat(generation, {"model": "mistral-small-latest"})
    assert generation.message_completion == {"role": "assistant", "content": "Hello!"}
    assert generation.tt_first_token is not None
    assert generation.token_throughput_in_s is not None
    _assert_timing(generation, timing)


@pytest.mark.parametrize("event_stream", [False, True])
async def test_chat_stream_async(generations, sdk, event_stream):
    sdk.event_stream = event_stream

    stream = await sdk.chat.stream_async(
        model="mistral-small-latest", messages=MESSAGES
    )
    events = [event async for event in stream]

    assert events == TEXT_EVENTS
    generation, timing = generations[0]
    _assert_chat(generation, {"model": "mistral-small-latest"})
    assert generation.message_completion == {"role": "assistant", "content": "Hello!"}
    assert generation.tt_first_token is not None
    _assert_timing(generation, timing)


def test_chat_stream_tool_calls(generations, sdk):
    sdk.events = TOOL_CALL_EVENTS

    list(sdk.chat.stream(model="mistral-small-latest", messages=MESSAGES))

    generation, _ = generations[0]
    assert generation.message_completion == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
            }
        ],
    }


def test_fim_complete(generations, sdk):
    sdk.fim.complete(model="codestral-latest", prompt="def answer():", suffix="\n")

    generation, timing = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.provider == "mistralai"
    assert generation.prompt == "def answer():"
    assert generation.completion == "return 42"
    assert generation.settings == {"suffix": "\n", "model": RESPONSE_MODEL}
    assert generation.token_count == 10
    _assert_timing(generation, timing)


async def test_fim_complete_async(generations, sdk):
    await sdk.fim.complete_async(model="codestral-latest", prompt="def answer():")

    generation, _ = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.completion == "return 42"


@pytest.mark.parametrize("event_stream", [False, True])
def test_fim_stream(generations, sdk, event_stream):
    sdk.event_stream = event_stream

    list(sdk.fim.stream(model="codestral-latest", prompt="def answer():"))

    generation, timing = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.completion == "Hello!"
    assert generation.tt_first_token is not None
    _assert_timing(generation, timing)


@pytest.mark.parametrize("event_stream", [False, True])
async def test_fim_stream_async(generations, sdk, event_stream):
    sdk.event_stream = event_stream

    stream = await sdk.fim.stream_async(model="codestral-latest", prompt="x")
    [event async for event in stream]

    generation, _ = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.completion == "Hello!"


def test_instrumenting_twice_is_idempotent(generations, sdk):
    second: List[Any] = []
    mistral_instrumentation.instrument_mistralai(
        lambda generation, timing: second.append(1)
    )

    sdk.chat.complete(model="mistral-small-latest", messages=MESSAGES)

    assert len(generations) == 1
    assert second == []


def test_literalai_kwargs_are_stripped(generations, sdk):
    sdk.chat.complete(
        model="mistral-small-latest", messages=MESSAGES, literalai_tags=["tag"]
    )

    assert sdk.calls == [{"model": "mistral-small-latest", "messages": MESSAGES}]
    assert generations[0][0].tags == ["tag"]


def test_works_without_eventstreaming_module(sdk, monkeypatch):
    """Early mistralai 1.x releases have no EventStream classes."""
    monkeypatch.delitem(sys.modules, "mistralai.utils.eventstreaming")
    monkeypatch.delitem(sys.modules, "mistralai.utils")
    captured: List[Any] = []
    mistral_instrumentation.instrument_mistralai(
        lambda generation, timing: captured.append(generation)
    )

    list(sdk.chat.stream(model="mistral-small-latest", messages=MESSAGES))

    assert captured[0].message_completion["content"] == "Hello!"


def test_import_does_not_require_mistralai():
    # The module only imports mistralai lazily, inside instrument_mistralai().
    assert "mistralai" not in mistral_instrumentation.__dict__
