"""Data layers persist elements to storage with the same serving policy as
/project/file (CVE-2026-110699): normalized type, inline only when it
can't run script."""

from unittest.mock import AsyncMock, Mock

import pytest

from chainlit.data.chainlit_data_layer import ChainlitDataLayer
from chainlit.data.dynamodb import DynamoDBDataLayer
from chainlit.element import File

CASES = [
    # claimed mime, name, stored mime, stored Content-Disposition
    ("image/png", "p.png", "image/png", 'inline; filename="p.png"'),
    ("application/pdf", "r.pdf", "application/pdf", 'inline; filename="r.pdf"'),
    ("image/svg+xml", "e.svg", "image/svg+xml", 'attachment; filename="e.svg"'),
    ("text/html", "x.html", "text/html", 'attachment; filename="x.html"'),
    (
        "video/mp4, text/html",
        "v.mp4",
        "application/octet-stream",
        'attachment; filename="v.mp4"',
    ),
    (None, "d.bin", "application/octet-stream", 'attachment; filename="d.bin"'),
    (
        "text/plain",
        'a"; b.txt',
        "text/plain",
        "inline; filename*=utf-8''a%22%3B%20b.txt",
    ),
]


def _element(mime, name):
    return File(
        name=name,
        mime=mime,
        content=b"<svg><script>alert(1)</script></svg>",
        for_id="step-1",
    )


def _assert_stored(storage, mime, disposition):
    storage.upload_file.assert_awaited_once()
    kwargs = storage.upload_file.call_args.kwargs
    assert kwargs["mime"] == mime
    assert kwargs["content_disposition"] == disposition


@pytest.mark.asyncio
@pytest.mark.parametrize(("claimed", "name", "mime", "disposition"), CASES)
async def test_chainlit_data_layer(
    mock_chainlit_context, mock_storage_client, claimed, name, mime, disposition
):
    async with mock_chainlit_context:
        layer = ChainlitDataLayer(
            database_url="postgresql://fake", storage_client=mock_storage_client
        )
        layer.execute_query = AsyncMock(return_value=[{"id": "row"}])

        await layer.create_element(_element(claimed, name))

    _assert_stored(mock_storage_client, mime, disposition)


@pytest.mark.asyncio
@pytest.mark.parametrize(("claimed", "name", "mime", "disposition"), CASES)
async def test_dynamodb_data_layer(
    mock_chainlit_context, mock_storage_client, claimed, name, mime, disposition
):
    async with mock_chainlit_context:
        layer = DynamoDBDataLayer(
            table_name="t", client=Mock(), storage_provider=mock_storage_client
        )

        await layer.create_element(_element(claimed, name))

    _assert_stored(mock_storage_client, mime, disposition)
