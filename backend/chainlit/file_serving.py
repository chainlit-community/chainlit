"""How Chainlit serves files whose type a user may control.

Uploads carry whatever MIME type the uploader claimed. Serving them inline
with that type would let an uploaded HTML or SVG file run script on the
origin it is served from (CVE-2026-110699). This module decides, in one
place, the Content-Type and Content-Disposition for such files: for
`/project/file` responses, and for objects that data layers persist to a
storage provider.
"""

import re
from typing import Literal, Optional
from urllib.parse import quote

# Types rendered inline: browsers display them without running script.
# Notably absent: text/html, image/svg+xml, XML and JavaScript.
INLINE_SAFE_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/apng",
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
    }
)
INLINE_SAFE_MIME_PREFIXES = ("audio/", "video/")
# A single RFC 9110 `type/subtype` token. Anything else (a comma-separated
# list, which browsers may read as its last entry, or stray characters) is
# served as an opaque download.
_MIME_ESSENCE_RE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
)
_CHARSET_PARAM_RE = re.compile(
    r"^\s*charset\s*=\s*\"?([A-Za-z0-9._:-]{1,40})\"?\s*$", re.IGNORECASE
)


def mime_essence(mime: Optional[str]) -> str:
    """The lowercase `type/subtype` of a MIME type, without parameters."""
    return (mime or "").split(";", 1)[0].strip().lower()


def served_mime_type(claimed: Optional[str]) -> tuple[str, bool]:
    """Return the Content-Type to serve a file with, and whether it may be
    rendered inline."""
    essence, *params = (claimed or "").split(";")
    essence = essence.strip().lower()
    if not _MIME_ESSENCE_RE.match(essence):
        return "application/octet-stream", False
    inline = essence in INLINE_SAFE_MIME_TYPES or (
        essence.startswith(INLINE_SAFE_MIME_PREFIXES) and not essence.endswith("+xml")
    )
    # Keep a well-formed charset, so non-UTF-8 text isn't served as UTF-8
    # (Starlette adds `charset=utf-8` to text/* types that have none).
    for param in params:
        if match := _CHARSET_PARAM_RE.match(param):
            return f"{essence}; charset={match.group(1)}", inline
    return essence, inline


def content_disposition(
    disposition_type: Literal["inline", "attachment"], filename: Optional[str]
) -> str:
    """A Content-Disposition value; a filename that isn't plain ASCII is
    percent-encoded (RFC 6266 / RFC 8187), so it can't break the header."""
    if not filename:
        return disposition_type
    # safe="": RFC 8187 allows no literal "/" in an extended value.
    quoted = quote(filename, safe="")
    if quoted != filename:
        return f"{disposition_type}; filename*=utf-8''{quoted}"
    return f'{disposition_type}; filename="{filename}"'


def storage_object_headers(
    claimed_mime: Optional[str],
    filename: Optional[str],
    safe_disposition: Optional[Literal["inline", "attachment"]] = None,
) -> tuple[str, Optional[str]]:
    """The Content-Type and Content-Disposition to store a user-influenced
    file with in a storage provider (S3, GCS, Azure), which serves it with
    these.

    The type is normalized as for `/project/file`. A type that could run
    script is always an `attachment`. For the other types the disposition
    is `safe_disposition`, or None to set none (the provider's default,
    which browsers render inline).
    """
    mime, inline = served_mime_type(claimed_mime)
    disposition_type = safe_disposition if inline else "attachment"
    if disposition_type is None:
        return mime, None
    return mime, content_disposition(disposition_type, filename)
