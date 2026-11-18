"""Mistral AI instrumentation: patches `Chat` and `Fim` complete/stream methods
(sync and async) and reports each call as a generation through a callback.

Derived from the Apache-2.0 licensed `literalai` package
(literalai/instrumentation/mistralai.py), trimmed to the callback-only code path.
Targets the mistralai 1.x SDK layout (`mistralai.chat.Chat`, `mistralai.fim.Fim`).
`mistralai` is imported lazily: it is an optional dependency of Chainlit.
"""

import time
from collections.abc import AsyncGenerator, Generator
from importlib import import_module
from typing import Any, Dict, List, Tuple, Union

from chainlit._instrumentation import (
    MISTRALAI_PROVIDER,
    OnNewGeneration,
    check_on_new_generation,
    ensure_values_serializable,
)
from chainlit._instrumentation.wrappers import AfterContext, BeforeContext, wrap_all
from chainlit.generation import (
    ChatGeneration,
    CompletionGeneration,
    GenerationMessage,
    GenerationType,
)

APIS_TO_WRAP: List[Dict[str, Any]] = [
    {
        "module": "mistralai.chat",
        "object": "Chat",
        "method": "complete",
        "metadata": {
            "type": GenerationType.CHAT,
        },
        "async": False,
    },
    {
        "module": "mistralai.chat",
        "object": "Chat",
        "method": "stream",
        "metadata": {
            "type": GenerationType.CHAT,
        },
        "async": False,
    },
    {
        "module": "mistralai.chat",
        "object": "Chat",
        "method": "complete_async",
        "metadata": {
            "type": GenerationType.CHAT,
        },
        "async": True,
    },
    {
        "module": "mistralai.chat",
        "object": "Chat",
        "method": "stream_async",
        "metadata": {
            "type": GenerationType.CHAT,
        },
        "async": True,
    },
    {
        "module": "mistralai.fim",
        "object": "Fim",
        "method": "complete",
        "metadata": {
            "type": GenerationType.COMPLETION,
        },
        "async": False,
    },
    {
        "module": "mistralai.fim",
        "object": "Fim",
        "method": "stream",
        "metadata": {
            "type": GenerationType.COMPLETION,
        },
        "async": False,
    },
    {
        "module": "mistralai.fim",
        "object": "Fim",
        "method": "complete_async",
        "metadata": {
            "type": GenerationType.COMPLETION,
        },
        "async": True,
    },
    {
        "module": "mistralai.fim",
        "object": "Fim",
        "method": "stream_async",
        "metadata": {
            "type": GenerationType.COMPLETION,
        },
        "async": True,
    },
]

is_mistralai_instrumented = False


def _stream_types() -> Tuple[Tuple[type, ...], Tuple[type, ...]]:
    """Return the (sync, async) types `stream` / `stream_async` may return.

    Early mistralai 1.x releases return plain (async) generators; later 1.x
    releases return `mistralai.utils.eventstreaming.EventStream(Async)`, which
    are iterators but not generators.
    """
    sync_types: Tuple[type, ...] = (Generator,)
    async_types: Tuple[type, ...] = (AsyncGenerator,)
    try:
        eventstreaming = import_module("mistralai.utils.eventstreaming")
    except ImportError:
        return sync_types, async_types
    if event_stream := getattr(eventstreaming, "EventStream", None):
        sync_types += (event_stream,)
    if event_stream_async := getattr(eventstreaming, "EventStreamAsync", None):
        async_types += (event_stream_async,)
    return sync_types, async_types


def instrument_mistralai(on_new_generation: OnNewGeneration) -> None:
    """
    Instruments all Mistral AI LLM calls: `on_new_generation(generation, timing)`
    is called once per completed call (for streams: once the stream is exhausted).
    """
    global is_mistralai_instrumented
    if is_mistralai_instrumented:
        return

    check_on_new_generation(on_new_generation)

    def init_generation(
        generation_type: GenerationType, kwargs
    ) -> Union[ChatGeneration, CompletionGeneration]:
        # `literalai_metadata` / `literalai_tags` are stripped from the SDK call
        # (see wrappers.remove_literalai_args) but still recorded on the
        # generation, as the original instrumentation did.
        model = kwargs.get("model")
        tools = kwargs.get("tools")

        if generation_type == GenerationType.CHAT:
            orig_messages = kwargs.get("messages")

            messages = ensure_values_serializable(orig_messages)
            prompt_id = None
            variables = None

            # `__literal_prompt__` is set on messages formatted by a LiteralAI
            # prompt template; kept from the original for compatibility.
            for index, message in enumerate(messages):
                orig_message = orig_messages[index]
                if literal_prompt := getattr(orig_message, "__literal_prompt__", None):
                    prompt_id = literal_prompt.get("prompt_id")
                    variables = literal_prompt.get("variables")
                    message["uuid"] = literal_prompt.get("uuid")
                    message["templated"] = True

            settings = {
                "model": model,
                "temperature": kwargs.get("temperature"),
                "top_p": kwargs.get("top_p"),
                "max_tokens": kwargs.get("max_tokens"),
                "stream": kwargs.get("stream"),
                "safe_prompt": kwargs.get("safe_prompt"),
                "random_seed": kwargs.get("random_seed"),
                "tool_choice": kwargs.get("tool_choice"),
                "response_format": kwargs.get("response_format"),
            }
            settings = {k: v for k, v in settings.items() if v is not None}
            return ChatGeneration(
                prompt_id=prompt_id,
                variables=variables,
                provider=MISTRALAI_PROVIDER,
                model=model,
                tools=tools,
                settings=settings,
                messages=messages,
                metadata=kwargs.get("literalai_metadata"),
                tags=kwargs.get("literalai_tags"),
            )
        else:
            settings = {
                "suffix": kwargs.get("suffix"),
                "model": model,
                "temperature": kwargs.get("temperature"),
                "top_p": kwargs.get("top_p"),
                "max_tokens": kwargs.get("max_tokens"),
                "min_tokens": kwargs.get("min_tokens"),
                "stream": kwargs.get("stream"),
                "random_seed": kwargs.get("random_seed"),
                "stop": kwargs.get("stop"),
            }
            settings = {k: v for k, v in settings.items() if v is not None}
            return CompletionGeneration(
                provider=MISTRALAI_PROVIDER,
                prompt=kwargs.get("prompt"),
                model=model,
                settings=settings,
                metadata=kwargs.get("literalai_metadata"),
                tags=kwargs.get("literalai_tags"),
            )

    def update_generation_after(
        generation: Union[ChatGeneration, CompletionGeneration], result
    ) -> None:
        if isinstance(generation, ChatGeneration):
            generation.message_completion = result.choices[0].message.model_dump()
        elif isinstance(generation, CompletionGeneration):
            generation.completion = result.choices[0].message.content

        generation.input_token_count = result.usage.prompt_tokens
        generation.output_token_count = result.usage.completion_tokens
        generation.token_count = result.usage.total_tokens

    def before_wrapper(metadata: Dict):
        def before(context: BeforeContext, *args, **kwargs):
            context["generation"] = init_generation(metadata["type"], kwargs)
            context["start"] = time.time()

        return before

    def async_before_wrapper(metadata: Dict):
        async def before(context: BeforeContext, *args, **kwargs):
            context["generation"] = init_generation(metadata["type"], kwargs)
            context["start"] = time.time()

        return before

    def process_delta(new_delta, message_completion: GenerationMessage) -> bool:
        if new_delta.tool_calls:
            if "tool_calls" not in message_completion:
                message_completion["tool_calls"] = []
            delta_tool_call = new_delta.tool_calls[0]
            delta_function = delta_tool_call.function
            if not delta_function:
                return False
            if delta_function.name:
                message_completion["tool_calls"].append(  # type: ignore[union-attr]
                    {
                        "id": delta_tool_call.id,
                        "type": "function",
                        "function": {
                            "name": delta_function.name,
                            "arguments": "",
                        },
                    }
                )
            if delta_function.arguments:
                message_completion["tool_calls"][-1]["function"][  # type: ignore[index]
                    "arguments"
                ] += delta_function.arguments

            return True
        elif new_delta.content:
            if isinstance(message_completion["content"], str):
                if isinstance(new_delta.content, str):
                    message_completion["content"] += new_delta.content
                    return True
            return False
        else:
            return False

    def finish_streaming(
        generation: Union[ChatGeneration, CompletionGeneration],
        context: AfterContext,
        token_count: int,
        message_completion: GenerationMessage,
        completion: str,
    ) -> None:
        generation.duration = time.time() - context["start"]
        if generation.duration and token_count:
            generation.token_throughput_in_s = token_count / generation.duration
        if isinstance(generation, ChatGeneration):
            generation.message_completion = message_completion
        else:
            generation.completion = completion

        on_new_generation(
            generation,
            {
                "start": context["start"],
                "end": time.time(),
            },
        )

    def streaming_response(
        generation: Union[ChatGeneration, CompletionGeneration],
        result,
        context: AfterContext,
    ):
        completion = ""
        message_completion: GenerationMessage = {
            "role": "assistant",
            "content": "",
        }
        token_count = 0
        for chunk in result:
            if isinstance(generation, ChatGeneration):
                if len(chunk.data.choices) > 0:
                    ok = process_delta(chunk.data.choices[0].delta, message_completion)
                    if not ok:
                        yield chunk
                        continue
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
            elif isinstance(generation, CompletionGeneration):
                if (
                    len(chunk.data.choices) > 0
                    and chunk.data.choices[0].delta.content is not None
                ):
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
                    completion += str(chunk.data.choices[0].delta.content)

            # Kept from the original: stream events carry the model on
            # `chunk.data`, not on `chunk`, so this never fires in practice.
            if getattr(chunk, "model", None) and generation.model != chunk.data.model:
                generation.model = chunk.data.model

            yield chunk

        finish_streaming(
            generation, context, token_count, message_completion, completion
        )

    async def async_streaming_response(
        generation: Union[ChatGeneration, CompletionGeneration],
        result,
        context: AfterContext,
    ):
        completion = ""
        message_completion: GenerationMessage = {
            "role": "assistant",
            "content": "",
        }
        token_count = 0
        async for chunk in result:
            if isinstance(generation, ChatGeneration):
                if len(chunk.data.choices) > 0:
                    ok = process_delta(chunk.data.choices[0].delta, message_completion)
                    if not ok:
                        yield chunk
                        continue
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
            elif isinstance(generation, CompletionGeneration):
                if (
                    len(chunk.data.choices) > 0
                    and chunk.data.choices[0].delta is not None
                ):
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
                    if isinstance(chunk.data.choices[0].delta.content, str):
                        completion += chunk.data.choices[0].delta.content or ""

            # See streaming_response: kept from the original.
            if getattr(chunk, "model", None) and generation.model != chunk.data.model:
                generation.model = chunk.data.model

            yield chunk

        finish_streaming(
            generation, context, token_count, message_completion, completion
        )

    sync_stream_types, async_stream_types = _stream_types()

    def handle_result(result, context: AfterContext, stream_types, streaming_fn):
        generation = context.get("generation")

        if not generation:
            return result

        if model := getattr(result, "model", None):
            generation.model = model
            if generation.settings:
                generation.settings["model"] = model

        if isinstance(result, stream_types):
            return streaming_fn(generation, result, context)

        generation.duration = time.time() - context["start"]
        update_generation_after(generation, result)

        on_new_generation(
            generation,
            {
                "start": context["start"],
                "end": time.time(),
            },
        )
        return result

    def after_wrapper(metadata: Dict):
        # Needs to be done in a separate function to avoid transforming all returned data into generators
        def after(result, context: AfterContext, *args, **kwargs):
            return handle_result(result, context, sync_stream_types, streaming_response)

        return after

    def async_after_wrapper(metadata: Dict):
        async def after(result, context: AfterContext, *args, **kwargs):
            return handle_result(
                result, context, async_stream_types, async_streaming_response
            )

        return after

    wrap_all(
        APIS_TO_WRAP,
        before_wrapper,
        after_wrapper,
        async_before_wrapper,
        async_after_wrapper,
    )

    is_mistralai_instrumented = True
