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
        # active documents are also stored with an opaque type
        (
            "text/html",
            "inline",
            ("application/octet-stream", 'attachment; filename="f"'),
        ),
        (
            "application/rss+xml",
            None,
            ("application/octet-stream", 'attachment; filename="f"'),
        ),
        ("text/xml", None, ("application/octet-stream", 'attachment; filename="f"')),
        (
            "multipart/x-mixed-replace",
            None,
            ("application/octet-stream", 'attachment; filename="f"'),
        ),
        # not an active document: keeps its type, but is a download
        ("application/json", None, ("application/json", 'attachment; filename="f"')),
        (
            "video/mp4, text/html",
            None,
            ("application/octet-stream", 'attachment; filename="f"'),
        ),
    ],
)
def test_storage_object_headers(claimed, safe_disposition, expected):
    assert storage_object_headers(claimed, "f", safe_disposition) == expected


def test_content_disposition_survives_a_lone_surrogate():
    assert content_disposition("attachment", "a\udc80.html") == (
        "attachment; filename*=utf-8''a%3F.html"
    )


def test_content_disposition_bounds_the_filename():
    value = content_disposition("attachment", "é" * 1000)
    assert value.startswith("attachment; filename*=utf-8''")
    assert value.count("%C3%A9") == 200


def test_content_disposition_keeps_the_extension_when_truncating():
    value = content_disposition("attachment", "a" * 199 + "é.html")
    assert value.rstrip('"').endswith(".html")
    assert len(value) < 700
