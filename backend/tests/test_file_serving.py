import pytest

from chainlit.file_serving import (
    content_disposition,
    mime_essence,
    served_mime_type,
    storage_object_headers,
)


@pytest.mark.parametrize(
    ("claimed", "expected"),
    [
        ("image/png", ("image/png", True)),
        ("IMAGE/PNG ", ("image/png", True)),
        ("application/pdf", ("application/pdf", True)),
        ("text/plain; charset=iso-8859-1", ("text/plain; charset=iso-8859-1", True)),
        ("audio/mpeg", ("audio/mpeg", True)),
        ("video/x-evil+xml", ("video/x-evil+xml", False)),
        ("image/svg+xml", ("image/svg+xml", False)),
        ("text/html", ("text/html", False)),
        ("video/mp4, text/html", ("application/octet-stream", False)),
        ("", ("application/octet-stream", False)),
        (None, ("application/octet-stream", False)),
    ],
)
def test_served_mime_type(claimed, expected):
    assert served_mime_type(claimed) == expected


@pytest.mark.parametrize(
    ("mime", "expected"),
    [("Image/PNG; x=1", "image/png"), (None, ""), ("text/html; x=image", "text/html")],
)
def test_mime_essence(mime, expected):
    assert mime_essence(mime) == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report.pdf", 'inline; filename="report.pdf"'),
        (None, "inline"),
        ("", "inline"),
        ('a"b.pdf', "inline; filename*=utf-8''a%22b.pdf"),
        (
            "x\r\nSet-Cookie: a=b",
            "inline; filename*=utf-8''x%0D%0ASet-Cookie%3A%20a%3Db",
        ),
        ("résumé.pdf", "inline; filename*=utf-8''r%C3%A9sum%C3%A9.pdf"),
        ("reports/r.pdf", "inline; filename*=utf-8''reports%2Fr.pdf"),
    ],
)
def test_content_disposition_encodes_the_filename(filename, expected):
    assert content_disposition("inline", filename) == expected


@pytest.mark.parametrize(
    ("claimed", "safe_disposition", "expected"),
    [
        ("image/png", None, ("image/png", None)),
        ("image/png", "inline", ("image/png", 'inline; filename="f"')),
        ("image/png", "attachment", ("image/png", 'attachment; filename="f"')),
        # script-capable or malformed: always an attachment
        ("image/svg+xml", None, ("image/svg+xml", 'attachment; filename="f"')),
        ("text/html", "inline", ("text/html", 'attachment; filename="f"')),
        (
            "video/mp4, text/html",
            None,
            ("application/octet-stream", 'attachment; filename="f"'),
        ),
    ],
)
def test_storage_object_headers(claimed, safe_disposition, expected):
    assert storage_object_headers(claimed, "f", safe_disposition) == expected
