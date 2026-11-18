"""Generic before/after wrappers used to patch LLM SDK methods.

Derived from the Apache-2.0 licensed `literalai` package (literalai/wrappers.py).
"""

import time
from functools import wraps
from importlib import import_module
from typing import Any, Callable, Dict, List, Optional, TypedDict, Union

from chainlit.generation import ChatGeneration, CompletionGeneration


class BeforeContext(TypedDict, total=False):
    original_func: Callable
    generation: Optional[Union[ChatGeneration, CompletionGeneration]]
    start: float


class AfterContext(TypedDict, total=False):
    original_func: Callable
    generation: Optional[Union[ChatGeneration, CompletionGeneration]]
    start: float


def remove_literalai_args(kargs: Dict[str, Any]) -> Dict[str, Any]:
    """Remove argument prefixed with "literalai_" from kwargs and return them in a separate dict.

    Kept for backward compatibility: code written for the LiteralAI
    instrumentation may pass `literalai_tags=` / `literalai_metadata=` to the SDK
    call, which the SDK itself would reject.

    This compatibility shim might be removed in a future release; new code
    should not pass `literalai_*` arguments.
    """
    largs = {}
    for key in list(kargs.keys()):
        if key.startswith("literalai_"):
            value = kargs.pop(key)
            largs[key] = value
    return largs


def restore_literalai_args(kargs: Dict[str, Any], largs: Dict[str, Any]) -> None:
    """Reverse the effect of remove_literalai_args by merging the literal arguments into kwargs"""
    for key in list(largs.keys()):
        kargs[key] = largs[key]


def sync_wrapper(before_func=None, after_func=None):
    def decorator(original_func):
        @wraps(original_func)
        def wrapped(*args, **kwargs):
            context: BeforeContext = {"original_func": original_func}
            # If a before_func is provided, call it with the shared context.
            if before_func:
                before_func(context, *args, **kwargs)
            # Remove literal arguments before calling the original function
            literalai_args = remove_literalai_args(kwargs)
            context["start"] = time.time()
            result = original_func(*args, **kwargs)
            # If an after_func is provided, call it with the result and the shared context.
            if after_func:
                restore_literalai_args(kwargs, literalai_args)
                result = after_func(result, context, *args, **kwargs)

            return result

        return wrapped

    return decorator


def async_wrapper(before_func=None, after_func=None):
    def decorator(original_func):
        @wraps(original_func)
        async def wrapped(*args, **kwargs):
            context: BeforeContext = {"original_func": original_func}
            # If a before_func is provided, call it with the shared context.
            if before_func:
                await before_func(context, *args, **kwargs)

            # Remove literal arguments before calling the original function
            literalai_args = remove_literalai_args(kwargs)
            context["start"] = time.time()
            result = await original_func(*args, **kwargs)

            # If an after_func is provided, call it with the result and the shared context.
            if after_func:
                restore_literalai_args(kwargs, literalai_args)
                result = await after_func(result, context, *args, **kwargs)

            return result

        return wrapped

    return decorator


def wrap_all(
    to_wrap: List[Dict[str, Any]],
    before_wrapper,
    after_wrapper,
    async_before_wrapper,
    async_after_wrapper,
) -> None:
    for patch in to_wrap:
        module = import_module(str(patch["module"]))
        target_object = getattr(module, str(patch["object"]))
        original_method = getattr(target_object, str(patch["method"]))

        if patch["async"]:
            wrapped_method = async_wrapper(
                before_func=async_before_wrapper(metadata=patch["metadata"]),
                after_func=async_after_wrapper(metadata=patch["metadata"]),
            )(original_method)
        else:
            wrapped_method = sync_wrapper(
                before_func=before_wrapper(metadata=patch["metadata"]),
                after_func=after_wrapper(metadata=patch["metadata"]),
            )(original_method)

        setattr(target_object, str(patch["method"]), wrapped_method)
