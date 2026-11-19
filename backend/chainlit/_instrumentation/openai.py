"""OpenAI instrumentation: patches the chat and legacy completion `create` methods
and reports each call as a generation through a callback.

Derived from the Apache-2.0 licensed `literalai` package
(literalai/instrumentation/openai.py), trimmed to the callback-only code path.
`openai` is imported lazily: it is an optional dependency of Chainlit.
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Union

from chainlit._instrumentation import (
    OPENAI_PROVIDER,
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

if TYPE_CHECKING:
    from openai.types.chat.chat_completion_chunk import ChoiceDelta

TO_WRAP: List[Dict[str, Any]] = [
    {
        "module": "openai.resources.chat.completions",
        "object": "Completions",
        "method": "create",
        "metadata": {
            "type": GenerationType.CHAT,
        },
        "async": False,
    },
    {
        "module": "openai.resources.completions",
        "object": "Completions",
        "method": "create",
        "metadata": {
            "type": GenerationType.COMPLETION,
        },
        "async": False,
    },
    {
        "module": "openai.resources.chat.completions",
        "object": "AsyncCompletions",
        "method": "create",
        "metadata": {
            "type": GenerationType.CHAT,
        },
        "async": True,
    },
    {
        "module": "openai.resources.completions",
        "object": "AsyncCompletions",
        "method": "create",
        "metadata": {
            "type": GenerationType.COMPLETION,
        },
        "async": True,
    },
]

is_openai_instrumented = False


def instrument_openai(on_new_generation: OnNewGeneration) -> None:
    """
    Instruments all OpenAI LLM calls: `on_new_generation(generation, timing)` is
    called once per completed call (for streams: once the stream is exhausted).
    """
    global is_openai_instrumented
    if is_openai_instrumented:
        return

    check_on_new_generation(on_new_generation)

    from openai import AsyncStream, Stream

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
                "frequency_penalty": kwargs.get("frequency_penalty"),
                "logit_bias": kwargs.get("logit_bias"),
                "logprobs": kwargs.get("logprobs"),
                "top_logprobs": kwargs.get("top_logprobs"),
                "max_tokens": kwargs.get("max_tokens"),
                "n": kwargs.get("n"),
                "presence_penalty": kwargs.get("presence_penalty"),
                "response_format": kwargs.get("response_format"),
                "seed": kwargs.get("seed"),
                "stop": kwargs.get("stop"),
                "stream": kwargs.get("stream"),
                "temperature": kwargs.get("temperature"),
                "top_p": kwargs.get("top_p"),
                "tool_choice": kwargs.get("tool_choice"),
            }
            settings = {k: v for k, v in settings.items() if v is not None}
            return ChatGeneration(
                prompt_id=prompt_id,
                variables=variables,
                provider=OPENAI_PROVIDER,
                model=model,
                tools=tools,
                settings=settings,
                messages=messages,
                metadata=kwargs.get("literalai_metadata"),
                tags=kwargs.get("literalai_tags"),
            )

        else:
            settings = {
                "model": model,
                "best_of": kwargs.get("best_of"),
                "echo": kwargs.get("echo"),
                "frequency_penalty": kwargs.get("frequency_penalty"),
                "logit_bias": kwargs.get("logit_bias"),
                "logprobs": kwargs.get("logprobs"),
                "max_tokens": kwargs.get("max_tokens"),
                "n": kwargs.get("n"),
                "presence_penalty": kwargs.get("presence_penalty"),
                "seed": kwargs.get("seed"),
                "stop": kwargs.get("stop"),
                "stream": kwargs.get("stream"),
                "suffix": kwargs.get("suffix"),
                "temperature": kwargs.get("temperature"),
                "top_p": kwargs.get("top_p"),
            }
            settings = {k: v for k, v in settings.items() if v is not None}
            return CompletionGeneration(
                provider=OPENAI_PROVIDER,
                model=model,
                settings=settings,
                prompt=kwargs.get("prompt"),
                metadata=kwargs.get("literalai_metadata"),
                tags=kwargs.get("literalai_tags"),
            )

    def update_generation_after(
        generation: Union[ChatGeneration, CompletionGeneration], result
    ) -> None:
        if isinstance(generation, ChatGeneration):
            generation.message_completion = result.choices[0].message.model_dump()
        elif isinstance(generation, CompletionGeneration):
            generation.completion = result.choices[0].text

        # `usage` is optional in the OpenAI response models (some
        # OpenAI-compatible servers omit it).
        if result.usage is not None:
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

    def process_delta(
        new_delta: "ChoiceDelta", message_completion: GenerationMessage
    ) -> bool:
        if new_delta.function_call:
            if new_delta.function_call.name:
                message_completion["function_call"] = {
                    "name": new_delta.function_call.name
                }

            if not message_completion["function_call"]:
                return False

            if new_delta.function_call.arguments:
                if "arguments" not in message_completion["function_call"]:
                    message_completion["function_call"]["arguments"] = ""
                message_completion["function_call"]["arguments"] += (
                    new_delta.function_call.arguments
                )
            return True
        elif new_delta.tool_calls:
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
                message_completion["tool_calls"][delta_tool_call.index]["function"][  # type: ignore[index]
                    "arguments"
                ] += delta_function.arguments

            return True
        elif new_delta.content:
            if isinstance(message_completion["content"], str):
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
                if len(chunk.choices) > 0:
                    ok = process_delta(chunk.choices[0].delta, message_completion)
                    if not ok:
                        yield chunk
                        continue
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
            elif isinstance(generation, CompletionGeneration):
                if len(chunk.choices) > 0 and chunk.choices[0].text is not None:
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
                    completion += chunk.choices[0].text

            if getattr(chunk, "model", None) and generation.model != chunk.model:
                generation.model = chunk.model
                if generation.settings:
                    generation.settings["model"] = chunk.model

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
                if len(chunk.choices) > 0:
                    ok = process_delta(chunk.choices[0].delta, message_completion)
                    if not ok:
                        yield chunk
                        continue
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
            elif isinstance(generation, CompletionGeneration):
                if len(chunk.choices) > 0 and chunk.choices[0].text is not None:
                    if generation.tt_first_token is None:
                        generation.tt_first_token = (
                            time.time() - context["start"]
                        ) * 1000
                    token_count += 1
                    completion += chunk.choices[0].text

            # Unlike the sync variant, the original did not update
            # settings["model"] here; kept as is.
            if getattr(chunk, "model", None) and generation.model != chunk.model:
                generation.model = chunk.model

            yield chunk

        finish_streaming(
            generation, context, token_count, message_completion, completion
        )

    def handle_result(result, context: AfterContext, stream_type, streaming_fn):
        generation = context.get("generation")

        if not generation:
            return result

        if model := getattr(result, "model", None):
            generation.model = model
            if generation.settings:
                generation.settings["model"] = model

        if isinstance(result, stream_type):
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
            return handle_result(result, context, Stream, streaming_response)

        return after

    def async_after_wrapper(metadata: Dict):
        async def after(result, context: AfterContext, *args, **kwargs):
            return handle_result(result, context, AsyncStream, async_streaming_response)

        return after

    wrap_all(
        TO_WRAP,
        before_wrapper,
        after_wrapper,
        async_before_wrapper,
        async_after_wrapper,
    )

    is_openai_instrumented = True
