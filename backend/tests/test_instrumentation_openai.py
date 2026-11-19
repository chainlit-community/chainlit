"""Tests for the vendored OpenAI instrumentation behind `cl.instrument_openai()`.

The real `openai` SDK is used, with its HTTP layer replaced by an
`httpx.MockTransport`, so the patched `create` methods see genuine response,
`Stream` and `AsyncStream` objects.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest

openai = pytest.importorskip("openai")

from chainlit._instrumentation import openai as openai_instrumentation  # noqa: E402
from chainlit.generation import ChatGeneration, CompletionGeneration  # noqa: E402

USAGE = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
RESPONSE_MODEL = "gpt-4o-mini-2024-07-18"
MESSAGES = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Say hello"},
]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _chat_completion(message: Dict[str, Any], usage: Optional[Dict] = USAGE) -> Dict:
    body: Dict[str, Any] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": RESPONSE_MODEL,
        "choices": [
            {"index": 0, "message": message, "finish_reason": "stop", "logprobs": None}
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _chat_chunk(delta: Dict[str, Any], finish_reason: Optional[str] = None) -> Dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": RESPONSE_MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _completion(text: str) -> Dict:
    return {
        "id": "cmpl-1",
        "object": "text_completion",
        "created": 1700000000,
        "model": "gpt-3.5-turbo-instruct-0914",
        "choices": [
            {"index": 0, "text": text, "finish_reason": "stop", "logprobs": None}
        ],
        "usage": USAGE,
    }


def _completion_chunk(text: str) -> Dict:
    return {
        "id": "cmpl-1",
        "object": "text_completion",
        "created": 1700000000,
        "model": "gpt-3.5-turbo-instruct-0914",
        "choices": [
            {"index": 0, "text": text, "finish_reason": None, "logprobs": None}
        ],
    }


def _sse(chunks: List[Dict]) -> bytes:
    events = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    events.append("data: [DONE]\n\n")
    return "".join(events).encode()


TEXT_CHUNKS = [
    _chat_chunk({"role": "assistant", "content": ""}),
    _chat_chunk({"content": "Hel"}),
    _chat_chunk({"content": "lo!"}),
    _chat_chunk({}, finish_reason="stop"),
]

TOOL_CALL_CHUNKS = [
    _chat_chunk({"role": "assistant", "content": None}),
    _chat_chunk(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": ""},
                }
            ]
        }
    ),
    _chat_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"city":'}}]}),
    _chat_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]}),
    _chat_chunk({}, finish_reason="tool_calls"),
]


class MockOpenAIServer:
    """Answers chat/legacy completion requests and records the request bodies."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.chat_message: Dict[str, Any] = {"role": "assistant", "content": "Hello!"}
        self.chat_chunks: List[Dict] = TEXT_CHUNKS
        self.usage: Optional[Dict] = USAGE

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        is_chat = request.url.path.endswith("/chat/completions")
        if body.get("stream"):
            chunks = (
                self.chat_chunks
                if is_chat
                else [_completion_chunk("Once"), _completion_chunk(" upon")]
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(chunks),
            )
        if is_chat:
            return httpx.Response(
                200, json=_chat_completion(self.chat_message, self.usage)
            )
        return httpx.Response(200, json=_completion("Once upon a time"))

    def sync_client(self):
        return openai.OpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )

    def async_client(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return self.handler(request)

        return openai.AsyncOpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )


def _patch_targets():
    from importlib import import_module

    for patch in openai_instrumentation.TO_WRAP:
        target = getattr(import_module(patch["module"]), patch["object"])
        yield target, patch["method"]


@pytest.fixture
def restore_openai():
    """Undo the monkey-patching and reset the idempotence guard afterwards."""
    originals = [
        (target, method, getattr(target, method)) for target, method in _patch_targets()
    ]
    openai_instrumentation.is_openai_instrumented = False
    yield
    for target, method, original in originals:
        setattr(target, method, original)
    openai_instrumentation.is_openai_instrumented = False


@pytest.fixture
def generations(restore_openai) -> List[Tuple[Any, Dict[str, float]]]:
    captured: List[Tuple[Any, Dict[str, float]]] = []

    def on_new_generation(generation, timing):
        captured.append((generation, timing))

    openai_instrumentation.instrument_openai(on_new_generation)
    return captured


@pytest.fixture
def server() -> MockOpenAIServer:
    return MockOpenAIServer()


def _assert_timing(generation, timing):
    assert set(timing) == {"start", "end"}
    assert timing["start"] <= timing["end"]
    assert generation.duration is not None
    assert generation.duration >= 0


def _assert_chat_basics(generation, stream: bool):
    assert isinstance(generation, ChatGeneration)
    assert generation.provider == "openai"
    assert generation.model == RESPONSE_MODEL
    assert generation.messages == MESSAGES
    expected_settings = {"model": RESPONSE_MODEL, "temperature": 0.2, "max_tokens": 5}
    if stream:
        expected_settings["stream"] = True
    assert generation.settings == expected_settings


def test_sync_chat(generations, server):
    client = server.sync_client()

    result = client.chat.completions.create(
        model="gpt-4o-mini", messages=MESSAGES, temperature=0.2, max_tokens=5
    )

    assert result.choices[0].message.content == "Hello!"
    assert len(generations) == 1
    generation, timing = generations[0]
    _assert_chat_basics(generation, stream=False)
    assert generation.message_completion["role"] == "assistant"
    assert generation.message_completion["content"] == "Hello!"
    assert generation.input_token_count == 7
    assert generation.output_token_count == 3
    assert generation.token_count == 10
    _assert_timing(generation, timing)
    assert generation.to_dict()["messageCompletion"]["content"] == "Hello!"


async def test_async_chat(generations, server):
    client = server.async_client()

    result = await client.chat.completions.create(
        model="gpt-4o-mini", messages=MESSAGES, temperature=0.2, max_tokens=5
    )

    assert result.choices[0].message.content == "Hello!"
    assert len(generations) == 1
    generation, timing = generations[0]
    _assert_chat_basics(generation, stream=False)
    assert generation.message_completion["content"] == "Hello!"
    assert generation.token_count == 10
    _assert_timing(generation, timing)


def test_sync_chat_tool_calls(generations, server):
    server.chat_message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
            }
        ],
    }
    client = server.sync_client()

    client.chat.completions.create(
        model="gpt-4o-mini", messages=MESSAGES, tools=TOOLS, tool_choice="auto"
    )

    generation, _ = generations[0]
    assert generation.tools == TOOLS
    assert generation.settings["tool_choice"] == "auto"
    assert generation.message_completion["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
        }
    ]


def test_sync_chat_stream(generations, server):
    client = server.sync_client()

    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=MESSAGES,
        temperature=0.2,
        max_tokens=5,
        stream=True,
    )
    # The generation is only reported once the stream has been consumed.
    assert generations == []
    chunks = list(stream)

    assert len(chunks) == len(TEXT_CHUNKS)
    assert len(generations) == 1
    generation, timing = generations[0]
    _assert_chat_basics(generation, stream=True)
    assert generation.message_completion == {"role": "assistant", "content": "Hello!"}
    assert generation.tt_first_token is not None
    assert generation.token_throughput_in_s is not None
    assert generation.token_count is None
    _assert_timing(generation, timing)


async def test_async_chat_stream(generations, server):
    client = server.async_client()

    stream = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=MESSAGES,
        temperature=0.2,
        max_tokens=5,
        stream=True,
    )
    assert generations == []
    chunks = [chunk async for chunk in stream]

    assert len(chunks) == len(TEXT_CHUNKS)
    assert len(generations) == 1
    generation, timing = generations[0]
    assert isinstance(generation, ChatGeneration)
    assert generation.model == RESPONSE_MODEL
    assert generation.message_completion == {"role": "assistant", "content": "Hello!"}
    assert generation.tt_first_token is not None
    _assert_timing(generation, timing)


def test_sync_chat_stream_tool_calls(generations, server):
    server.chat_chunks = TOOL_CALL_CHUNKS
    client = server.sync_client()

    list(
        client.chat.completions.create(
            model="gpt-4o-mini", messages=MESSAGES, tools=TOOLS, stream=True
        )
    )

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


def test_sync_completion(generations, server):
    client = server.sync_client()

    result = client.completions.create(
        model="gpt-3.5-turbo-instruct", prompt="Tell a story", max_tokens=5
    )

    assert result.choices[0].text == "Once upon a time"
    generation, timing = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.provider == "openai"
    assert generation.model == "gpt-3.5-turbo-instruct-0914"
    assert generation.prompt == "Tell a story"
    assert generation.completion == "Once upon a time"
    assert generation.settings == {
        "model": "gpt-3.5-turbo-instruct-0914",
        "max_tokens": 5,
    }
    assert generation.input_token_count == 7
    assert generation.output_token_count == 3
    assert generation.token_count == 10
    _assert_timing(generation, timing)


def test_sync_completion_stream(generations, server):
    client = server.sync_client()

    chunks = list(
        client.completions.create(
            model="gpt-3.5-turbo-instruct", prompt="Tell a story", stream=True
        )
    )

    assert len(chunks) == 2
    generation, timing = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.completion == "Once upon"
    assert generation.model == "gpt-3.5-turbo-instruct-0914"
    assert generation.settings["model"] == "gpt-3.5-turbo-instruct-0914"
    assert generation.settings["stream"] is True
    assert generation.tt_first_token is not None
    _assert_timing(generation, timing)


async def test_async_completion(generations, server):
    client = server.async_client()

    await client.completions.create(model="gpt-3.5-turbo-instruct", prompt="Hi")

    generation, _ = generations[0]
    assert isinstance(generation, CompletionGeneration)
    assert generation.completion == "Once upon a time"


async def test_async_completion_stream(generations, server):
    client = server.async_client()

    stream = await client.completions.create(
        model="gpt-3.5-turbo-instruct", prompt="Hi", stream=True
    )
    [chunk async for chunk in stream]

    generation, _ = generations[0]
    assert generation.completion == "Once upon"


def test_missing_usage_does_not_fail(generations, server):
    server.usage = None
    client = server.sync_client()

    client.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)

    generation, _ = generations[0]
    assert generation.token_count is None
    assert generation.input_token_count is None


def test_instrumenting_twice_is_idempotent(generations, server):
    second: List[Any] = []
    openai_instrumentation.instrument_openai(
        lambda generation, timing: second.append(1)
    )
    client = server.sync_client()

    client.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)

    assert len(generations) == 1
    assert second == []


def test_literalai_kwargs_are_stripped(generations, server):
    client = server.sync_client()

    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=MESSAGES,
        literalai_tags=["tag"],
        literalai_metadata={"key": "value"},
    )

    assert server.requests == [{"model": "gpt-4o-mini", "messages": MESSAGES}]
    generation, _ = generations[0]
    assert generation.tags == ["tag"]
    assert generation.metadata == {"key": "value"}


def test_callback_must_take_two_parameters(restore_openai):
    with pytest.raises(ValueError, match="should take 2 parameters"):
        openai_instrumentation.instrument_openai(lambda generation: None)
    assert openai_instrumentation.is_openai_instrumented is False


async def test_cl_instrument_openai_creates_llm_step(
    restore_openai, server, mock_chainlit_context, monkeypatch
):
    from chainlit.openai import instrument_openai
    from chainlit.step import Step

    sent: List[Step] = []

    async def fake_send(self):
        sent.append(self)
        return self

    monkeypatch.setattr(Step, "send", fake_send)

    async with mock_chainlit_context:
        instrument_openai()
        client = server.async_client()
        await client.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
        await asyncio.sleep(0)

    assert len(sent) == 1
    step = sent[0]
    assert step.type == "llm"
    assert step.name == RESPONSE_MODEL
    # Step serialises non-string input to JSON
    assert json.loads(step.input) == MESSAGES
    step_dict = step.to_dict()
    assert step_dict["generation"]["type"] == "CHAT"
    assert step_dict["generation"]["provider"] == "openai"
    assert step_dict["generation"]["messages"] == MESSAGES
    assert step_dict["generation"]["messageCompletion"]["content"] == "Hello!"
    assert step_dict["start"] is not None
    assert step_dict["end"] is not None
