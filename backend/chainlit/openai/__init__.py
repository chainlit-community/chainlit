import asyncio
from typing import Any

from chainlit.context import local_steps
from chainlit.step import Step
from chainlit.utils import check_module_version, timestamp_utc


def instrument_openai():
    if not check_module_version("openai", "1.0.0"):
        raise ValueError(
            "Expected OpenAI version >= 1.0.0. Run `pip install openai --upgrade`"
        )

    from literalai.instrumentation.openai import instrument_openai

    def on_new_generation(generation: Any, timing):
        previous_steps = local_steps.get()

        parent_id = previous_steps[-1].id if previous_steps else None

        step = Step(
            name=generation.model or generation.provider,
            type="llm",
            parent_id=parent_id,
        )
        step.generation = generation
        # Convert start/end time from seconds to milliseconds
        step.start = (
            timestamp_utc(timing.get("start"))
            if timing.get("start", None) is not None
            else None
        )
        step.end = (
            timestamp_utc(timing.get("end"))
            if timing.get("end", None) is not None
            else None
        )

        # Duck-typed: literalai.instrumentation still returns literalai's own
        # generation classes, so isinstance() against chainlit's would be False.
        # Vendoring the instrumentation restores an isinstance() check.
        if hasattr(generation, "messages"):
            step.input = generation.messages  # type: ignore
            step.output = generation.message_completion  # type: ignore
        else:
            step.input = generation.prompt  # type: ignore
            step.output = generation.completion  # type: ignore

        asyncio.create_task(step.send())

    instrument_openai(None, on_new_generation)
