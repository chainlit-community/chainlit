from typing import Dict, List, Optional

import chainlit as cl
from chainlit.data.base import BaseDataLayer
from chainlit.types import PageInfo, PaginatedResponse

# The debug button is only rendered in debug mode, which is normally enabled
# with `chainlit run -d`. The Cypress harness does not pass that flag, so the
# app switches it on itself (this runs before the server starts).
cl.config.config.run.debug = True


class DebugUrlDataLayer(BaseDataLayer):
    """Minimal no-op data layer exposing a debug URL template."""

    async def get_user(self, identifier):
        return None

    async def create_user(self, user):
        return None

    async def delete_feedback(self, feedback_id: str) -> bool:
        return True

    async def upsert_feedback(self, feedback) -> str:
        return ""

    async def create_element(self, element):
        pass

    async def get_element(self, thread_id: str, element_id: str):
        return None

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None):
        pass

    async def create_step(self, step_dict):
        pass

    async def update_step(self, step_dict):
        pass

    async def delete_step(self, step_id: str):
        pass

    async def get_thread_author(self, thread_id: str) -> str:
        return ""

    async def delete_thread(self, thread_id: str):
        pass

    async def list_threads(self, pagination, filters):
        return PaginatedResponse(
            pageInfo=PageInfo(hasNextPage=False, startCursor=None, endCursor=None),
            data=[],
        )

    async def get_thread(self, thread_id: str):
        return None

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ):
        pass

    async def build_debug_url(self) -> str:
        return "https://debug.example.com/threads/[thread_id]/steps/[step_id]"

    async def close(self) -> None:
        pass

    async def get_favorite_steps(self, user_id: str):
        return []


@cl.data_layer
def data_layer():
    return DebugUrlDataLayer()


@cl.on_message
async def on_message(message: cl.Message):
    await cl.Message(content="Hello from the debug button test").send()
