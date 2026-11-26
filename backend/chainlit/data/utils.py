import functools
import inspect
from collections import deque
from typing import TYPE_CHECKING, Literal, Optional, Union

from chainlit.context import context
from chainlit.file_serving import mime_essence, storage_object_headers
from chainlit.logger import logger
from chainlit.session import WebsocketSession

if TYPE_CHECKING:
    from chainlit.data.storage_clients.base import BaseStorageClient


def queue_until_user_message():
    def decorator(method):
        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            if (
                isinstance(context.session, WebsocketSession)
                and not context.session.has_first_interaction
            ):
                # Queue the method invocation waiting for the first user message
                queues = context.session.thread_queues
                method_name = method.__name__
                if method_name not in queues:
                    queues[method_name] = deque()
                queues[method_name].append((method, self, args, kwargs))

            else:
                # Otherwise, Execute the method immediately
                return await method(self, *args, **kwargs)

        return wrapper

    return decorator


def _accepts_content_disposition(upload_file) -> bool:
    try:
        params = inspect.signature(upload_file).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        or (
            p.name == "content_disposition"
            and p.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        )
        for p in params
    )


async def upload_element_file(
    storage: "BaseStorageClient",
    object_key: str,
    data: Union[bytes, str],
    mime: Optional[str],
    filename: Optional[str],
    safe_disposition: Optional[Literal["inline", "attachment"]] = None,
):
    """Upload an element's bytes with the serving policy of `/project/file`
    (CVE-2026-110699): see `storage_object_headers`."""
    stored_mime, disposition = storage_object_headers(mime, filename, safe_disposition)
    if disposition is None:
        return await storage.upload_file(
            object_key=object_key, data=data, mime=stored_mime, overwrite=True
        )
    if _accepts_content_disposition(storage.upload_file):
        return await storage.upload_file(
            object_key=object_key,
            data=data,
            mime=stored_mime,
            overwrite=True,
            content_disposition=disposition,
        )
    # A storage client written before `content_disposition` existed can't
    # make this a download. Active documents already have an opaque type;
    # SVG is the other type that runs script when opened, so it gets one
    # too. Other types keep theirs: the frontend parses application/json
    # responses (Plotly and dataframe elements).
    if mime_essence(stored_mime) == "image/svg+xml":
        logger.warning(
            "%s.upload_file takes no content_disposition; storing %r as "
            "application/octet-stream",
            type(storage).__name__,
            filename,
        )
        stored_mime = "application/octet-stream"
    return await storage.upload_file(
        object_key=object_key, data=data, mime=stored_mime, overwrite=True
    )
