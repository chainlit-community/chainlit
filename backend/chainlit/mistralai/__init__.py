import asyncio
from typing import Any

from chainlit.context import get_context
from chainlit.step import Step
from chainlit.utils import timestamp_utc


def instrument_mistralai():
    from literalai.instrumentation.mistralai import instrument_mistralai

    def on_new_generation(generation: Any, timing):
        context = get_context()

        parent_id = None
        if context.current_step:
            parent_id = context.current_step.id

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

    instrument_mistralai(None, on_new_generation)
