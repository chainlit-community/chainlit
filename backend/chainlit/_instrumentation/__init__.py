"""Monkey-patching instrumentation for LLM SDKs, backing `cl.instrument_openai()`
and `cl.instrument_mistralai()`.

Derived from the Apache-2.0 licensed `literalai` package
(literalai/instrumentation/__init__.py and literalai/helper.py), trimmed to the
callback-only code path Chainlit uses. Private: not part of Chainlit's public API.
"""

from typing import Any, Callable, Dict, Union

from pydantic import BaseModel

from chainlit.generation import ChatGeneration, CompletionGeneration

MISTRALAI_PROVIDER = "mistralai"
OPENAI_PROVIDER = "openai"

OnNewGeneration = Callable[
    [Union[ChatGeneration, CompletionGeneration], Dict[str, float]], Any
]


def _filter_none_values(data: Dict) -> Dict:
    return {key: value for key, value in data.items() if value is not None}


def ensure_values_serializable(data: Any) -> Any:
    """
    Recursively ensures that all values in the input (dict or list) are JSON serializable.
    """

    if isinstance(data, BaseModel):
        return _filter_none_values(data.model_dump())
    elif isinstance(data, dict):
        return {key: ensure_values_serializable(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [ensure_values_serializable(item) for item in data]
    elif isinstance(data, (str, int, float, bool, type(None))):
        return data
    elif isinstance(data, (tuple, set)):
        # Convert tuples and sets to lists
        return ensure_values_serializable(list(data))
    else:
        # Fallback: convert other types to string
        return str(data)


def check_on_new_generation(on_new_generation: OnNewGeneration) -> None:
    import inspect

    if callable(on_new_generation):
        sig = inspect.signature(on_new_generation)
        parameters = list(sig.parameters.values())

        if len(parameters) != 2:
            raise ValueError(
                "on_new_generation should take 2 parameters: generation and timing"
            )
