"""Data layers persist elements to storage with the same serving policy as
/project/file (CVE-2026-110699): normalized type, inline only when it
can't run script."""

from unittest.mock import AsyncMock, Mock

import pytest

from chainlit.data.chainlit_data_layer import ChainlitDataLayer
from chainlit.data.dynamodb import DynamoDBDataLayer
from chainlit.element import File

# claimed mime, name, stored mime, stored disposition for script-free types
# in the Chainlit data layer (always a download) and in the SQLAlchemy and
# DynamoDB ones (none set, as before)
CASES = [
    ("image/png", "p.png", "image/png", 'attachment; filename="p.png"', None),
    (
        "application/pdf",
        "r.pdf",
        "application/pdf",
        'attachment; filename="r.pdf"',
        None,
    ),
    # script-capable or malformed: an attachment everywhere
    *(
        (
            claimed,
            name,
            mime,
            f'attachment; filename="{name}"',
            f'attachment; filename="{name}"',
        )
        for claimed, name, mime in [
            ("image/svg+xml", "e.svg", "image/svg+xml"),
            ("text/html", "x.html", "application/octet-stream"),
            ("video/mp4, text/html", "v.mp4", "application/octet-stream"),
            (None, "d.bin", "application/octet-stream"),
        ]
    ),
    (
        "text/html",
        'a"; b.html',
        "application/octet-stream",
        "attachment; filename*=utf-8''a%22%3B%20b.html",
        "attachment; filename*=utf-8''a%22%3B%20b.html",
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
    assert kwargs.get("content_disposition") == disposition


@pytest.mark.asyncio
@pytest.mark.parametrize(("claimed", "name", "mime", "disposition", "_"), CASES)
async def test_chainlit_data_layer(
    mock_chainlit_context, mock_storage_client, claimed, name, mime, disposition, _
):
    async with mock_chainlit_context:
        layer = ChainlitDataLayer(
            database_url="postgresql://fake", storage_client=mock_storage_client
        )
        layer.execute_query = AsyncMock(return_value=[{"id": "row"}])

        await layer.create_element(_element(claimed, name))

    _assert_stored(mock_storage_client, mime, disposition)


@pytest.mark.asyncio
@pytest.mark.parametrize(("claimed", "name", "mime", "_", "disposition"), CASES)
async def test_dynamodb_data_layer(
    mock_chainlit_context, mock_storage_client, claimed, name, mime, _, disposition
):
    async with mock_chainlit_context:
        layer = DynamoDBDataLayer(
            table_name="t", client=Mock(), storage_provider=mock_storage_client
        )

        await layer.create_element(_element(claimed, name))

    _assert_stored(mock_storage_client, mime, disposition)


class LegacyStorageClient:
    """A custom client written before `content_disposition` existed."""

    def __init__(self):
        self.calls = []

    async def upload_file(
        self, object_key, data, mime="application/octet-stream", overwrite=True
    ):
        self.calls.append({"object_key": object_key, "mime": mime})
        return {"url": "https://example.com/x", "object_key": object_key}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claimed", "stored"),
    [
        ("image/png", "image/png"),
        # can't be made a download: stored with a type no browser renders
        ("image/svg+xml", "application/octet-stream"),
        ("text/html", "application/octet-stream"),
        # keeps its type: the frontend parses JSON responses (Plotly)
        ("application/json", "application/json"),
    ],
)
async def test_legacy_storage_client_still_works(
    mock_chainlit_context, claimed, stored
):
    storage = LegacyStorageClient()
    async with mock_chainlit_context:
        layer = DynamoDBDataLayer(
            table_name="t", client=Mock(), storage_provider=storage
        )

        await layer.create_element(_element(claimed, "f"))

    assert storage.calls == [
        {"object_key": storage.calls[0]["object_key"], "mime": stored}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claimed", "content_type", "disposition"),
    [
        ("image/svg+xml", "image/svg+xml", 'attachment; filename="f"'),
        ("text/html", "application/octet-stream", 'attachment; filename="f"'),
        ("image/png", "image/png", None),
    ],
)
async def test_object_metadata_in_s3(
    mock_chainlit_context, monkeypatch, claimed, content_type, disposition
):
    """End to end through the real S3 client (moto): what the bucket serves."""
    import boto3  # type: ignore
    from moto import mock_aws

    from chainlit.data.storage_clients.s3 import S3StorageClient

    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(key, value)

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        storage = S3StorageClient(bucket="test-bucket")
        async with mock_chainlit_context:
            layer = DynamoDBDataLayer(
                table_name="t", client=Mock(), storage_provider=storage
            )
            element = _element(claimed, "f")
            await layer.create_element(element)

        (obj,) = s3.list_objects_v2(Bucket="test-bucket")["Contents"]
        head = s3.head_object(Bucket="test-bucket", Key=obj["Key"])

    assert head["ContentType"] == content_type
    assert head.get("ContentDisposition") == disposition


class PositionalOnlyDispositionClient:
    """Takes a parameter called content_disposition, but not by keyword."""

    def __init__(self):
        self.calls = []

    async def upload_file(
        self, content_disposition=None, /, *, object_key, data, mime, overwrite
    ):
        self.calls.append(mime)
        return {"url": "https://example.com/x", "object_key": object_key}


class KwargsClient:
    def __init__(self):
        self.calls = []

    async def upload_file(self, **kwargs):
        self.calls.append(kwargs)
        return {"url": "https://example.com/x", "object_key": kwargs["object_key"]}


@pytest.mark.asyncio
async def test_positional_only_parameter_is_not_keyword_support():
    from chainlit.data.utils import upload_element_file

    storage = PositionalOnlyDispositionClient()

    await upload_element_file(storage, "k", b"x", "image/svg+xml", "e.svg")

    assert storage.calls == ["application/octet-stream"]


@pytest.mark.asyncio
async def test_kwargs_client_gets_the_disposition():
    from chainlit.data.utils import upload_element_file

    storage = KwargsClient()

    await upload_element_file(storage, "k", b"x", "image/svg+xml", "e.svg")

    assert storage.calls[0]["mime"] == "image/svg+xml"
    assert storage.calls[0]["content_disposition"] == 'attachment; filename="e.svg"'


def _legacy_behind_wrapper():
    """A pre-2.7.0 client whose upload_file is wrapped without
    functools.wraps, so its signature reads as (*args, **kwargs)."""
    legacy = LegacyStorageClient()
    inner = legacy.upload_file

    async def wrapper(*args, **kwargs):
        return await inner(*args, **kwargs)

    legacy.upload_file = wrapper  # type: ignore[method-assign]
    return legacy


@pytest.mark.asyncio
async def test_wrapped_legacy_client_falls_back():
    from chainlit.data.utils import upload_element_file

    storage = _legacy_behind_wrapper()

    await upload_element_file(storage, "k", b"x", "image/svg+xml", "e.svg")

    assert storage.calls == [{"object_key": "k", "mime": "application/octet-stream"}]


@pytest.mark.asyncio
async def test_unrelated_type_error_is_not_swallowed():
    from chainlit.data.utils import upload_element_file

    class Broken:
        async def upload_file(self, **kwargs):
            raise TypeError("something else")

    with pytest.raises(TypeError, match="something else"):
        await upload_element_file(Broken(), "k", b"x", "image/svg+xml", "e.svg")
