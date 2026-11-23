#!/usr/bin/env python3
"""Compute, stamp and record the version of a CI build.

Standard library only, so it runs before anything is installed:

    python scripts/ci_version.py stamp --write --build-info dist/build-info.json
    # ... build the wheel, the sdist and the react-client tarball into dist/ ...
    python scripts/ci_version.py finalize --dist dist

Versioning scheme, with ``base`` the release version in
``backend/chainlit/version.py`` (``3.0.0``, or a pre-release such as
``3.0.0rc1``) and ``N`` the number of commits reachable from HEAD:

* push to ``main``    -> ``<base>.dev<N>``
* anything else       -> ``<base>.dev<N>+<label>.g<sha7>``, the label being
  ``pr<number>`` for pull requests, ``mq`` for merge queues and the sanitized
  ref name otherwise
* ``@chainlit/react-client`` -> ``<package.json version>-dev.<N>``, or
  ``<package.json version>.dev.<N>`` when that version already is a
  pre-release (``0.5.0-rc.1`` -> ``0.5.0-rc.1.dev.<N>``)

``stamp`` prints the build metadata and, with ``--write``, rewrites
``version.py`` and the react-client ``package.json`` in place. ``finalize``
checks the built files against that metadata and writes ``SHA256SUMS``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = Path("backend", "chainlit", "version.py")
CLIENT_PACKAGE_JSON = Path("libs", "react-client", "package.json")
BUILD_INFO_NAME = "build-info.json"
CHECKSUMS_NAME = "SHA256SUMS"

# All patterns spell out [0-9]: \d would also match non-ASCII digits.
_NUMBER = r"(?:0|[1-9][0-9]*)"
# Canonical PEP 440 public version without epoch, .post, .dev or local part:
# two to four release components and an optional aN / bN / rcN pre-release.
BASE_VERSION_RE = re.compile(
    rf"{_NUMBER}(?:\.{_NUMBER}){{1,3}}(?:(?:a|b|rc){_NUMBER})?"
)
# semver X.Y.Z with an optional pre-release and no build metadata.
_SEMVER_IDENTIFIER = rf"(?:{_NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
CLIENT_VERSION_RE = re.compile(
    rf"{_NUMBER}(?:\.{_NUMBER}){{2}}"
    rf"(?:-(?P<prerelease>{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*))?"
)
# The pre-release identifier this script adds; a base that has it is stamped.
DEV_IDENTIFIER = "dev"
VERSION_PY_RE = re.compile(
    r"""^(__version__\s*=\s*)(["'])([^"']*)(["'])""", re.MULTILINE
)
PACKAGE_JSON_VERSION_RE = re.compile(r'^(\s*"version"\s*:\s*")([^"]*)(")', re.MULTILINE)
PR_REF_RE = re.compile(r"refs/pull/([0-9]+)/")
MAX_LABEL_LENGTH = 40


class VersionError(Exception):
    """A problem that must fail the build, reported without a traceback."""


def git(root: Path, *args: str) -> str | None:
    """Return the output of a git command, or None when it fails."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def read_base_version(root: Path) -> str:
    path = root / VERSION_FILE
    match = VERSION_PY_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise VersionError(f"No __version__ assignment found in {path}")
    version = match.group(3)
    if not BASE_VERSION_RE.fullmatch(version):
        raise VersionError(
            f"{VERSION_FILE.as_posix()} holds {version!r}, expected a release "
            "version in its canonical PEP 440 form, such as 3.0.0 or 3.0.0rc1: two "
            "to four numbers and an optional aN, bN or rcN pre-release (is the tree "
            "already stamped?)"
        )
    return version


def read_client_version(root: Path) -> str:
    path = root / CLIENT_PACKAGE_JSON
    version = json.loads(path.read_text(encoding="utf-8")).get("version")
    match = CLIENT_VERSION_RE.fullmatch(version) if isinstance(version, str) else None
    if not match or DEV_IDENTIFIER in (match["prerelease"] or "").split("."):
        raise VersionError(
            f"{CLIENT_PACKAGE_JSON.as_posix()} holds version {version!r}, expected "
            "a semver release version such as 0.5.0 or 0.5.0-rc.1 (is the tree "
            "already stamped?)"
        )
    return version


def stamp_client_version(base: str, number: int) -> str:
    """Append the build number as semver pre-release identifiers."""
    separator = "." if "-" in base else "-"
    return f"{base}{separator}{DEV_IDENTIFIER}.{number}"


def write_python_version(root: Path, version: str) -> None:
    path = root / VERSION_FILE
    text = path.read_text(encoding="utf-8")
    new_text, count = VERSION_PY_RE.subn(
        lambda m: f"{m.group(1)}{m.group(2)}{version}{m.group(4)}", text, count=1
    )
    if count != 1:
        raise VersionError(f"No __version__ assignment found in {path}")
    path.write_text(new_text, encoding="utf-8", newline="\n")


def write_client_version(root: Path, version: str) -> None:
    """Replace only the version string so the file keeps its formatting."""
    path = root / CLIENT_PACKAGE_JSON
    text = path.read_text(encoding="utf-8")
    new_text = PACKAGE_JSON_VERSION_RE.sub(
        lambda m: f"{m.group(1)}{version}{m.group(3)}", text, count=1
    )
    if json.loads(new_text).get("version") != version:
        raise VersionError(f'Could not rewrite the top-level "version" in {path}')
    path.write_text(new_text, encoding="utf-8", newline="\n")


def build_number(root: Path) -> int:
    if git(root, "rev-parse", "--is-shallow-repository") == "true":
        raise VersionError(
            "The repository is a shallow clone, so the commit count would be wrong. "
            "Fetch the full history (fetch-depth: 0) or pass --build-number."
        )
    count = git(root, "rev-list", "--count", "HEAD")
    if count is None or not re.fullmatch(r"[0-9]+", count):
        raise VersionError(
            "Could not count commits with git; pass --build-number instead."
        )
    return int(count)


def check_not_released(root: Path, base: str, *, strict: bool) -> None:
    """Refuse to publish dev versions of something that is already released.

    A tag named exactly like the base version means that version is out. Only
    the tagged commit itself (the release being cut) may still carry it; any
    later commit must bump version.py first, or its builds would sort *before*
    the release they come after.

    Only builds of main (``strict``) are refused, since those are published as
    preview releases. Other builds just warn, so pull requests keep building
    between a release and the version bump.
    """
    tagged = git(
        root, "rev-parse", "--quiet", "--verify", f"refs/tags/{base}^{{commit}}"
    )
    if not tagged:
        return
    if tagged == git(root, "rev-parse", "--verify", "HEAD^{commit}"):
        return
    message = (
        f"Tag {base} already exists but {VERSION_FILE.as_posix()} still says {base}. "
        "Bump __version__ to the next release."
    )
    if strict:
        raise VersionError(message)
    print(f"::warning::{message}", file=sys.stderr)


def sanitize_label(value: str) -> str:
    """Make a string usable as a PEP 440 local version label.

    Only ``[a-z0-9.]`` is allowed; everything else collapses to a single dot.
    Numeric segments lose their leading zeros, as packaging tools normalize
    them that way and the version must match the built file names.
    """
    label = re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")
    label = label[:MAX_LABEL_LENGTH].strip(".")
    return ".".join(
        str(int(part)) if part.isdigit() else part for part in label.split(".")
    )


def resolve_pr_number(pr_number: str | None, ref: str) -> int | None:
    if pr_number:
        # Not str.isdigit(): that accepts non-ASCII digits too.
        if not re.fullmatch(r"[0-9]+", pr_number):
            raise VersionError(f"Invalid pull request number: {pr_number!r}")
        return int(pr_number)
    match = PR_REF_RE.match(ref)
    return int(match.group(1)) if match else None


def local_label(event: str, ref: str, pr_number: int | None) -> str:
    if event in ("pull_request", "pull_request_target"):
        if pr_number is None:
            raise VersionError(
                "Pull request builds need the pull request number (--pr-number)."
            )
        return f"pr{pr_number}"
    if event == "merge_group":
        return "mq"
    ref_name = re.sub(r"^refs/(heads|tags|remotes/[^/]+)/", "", ref)
    return sanitize_label(ref_name) or sanitize_label(event) or "local"


def compute(
    root: Path,
    *,
    event: str,
    ref: str,
    sha: str,
    run_id: str | None = None,
    pr_number: str | None = None,
    number: int | None = None,
) -> dict:
    """Return the build metadata, in the build-info.json schema."""
    base = read_base_version(root)
    client_base = read_client_version(root)
    preview = event == "push" and ref == "refs/heads/main"
    check_not_released(root, base, strict=preview)

    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise VersionError(f"Expected a full 40 character commit SHA, got {sha!r}")
    if number is None:
        number = build_number(root)
    pr = resolve_pr_number(pr_number, ref)

    version = f"{base}.dev{number}"
    if not preview:
        version += f"+{local_label(event, ref, pr)}.g{sha[:7]}"
    client_version = stamp_client_version(client_base, number)

    return {
        "version": version,
        "client_version": client_version,
        "base_version": base,
        "build_number": number,
        "sha": sha,
        "ref": ref,
        "event": event,
        "pr_number": pr,
        "run_id": run_id,
        "files": {
            "wheel": f"chainlit-{version}-py3-none-any.whl",
            "sdist": f"chainlit-{version}.tar.gz",
            "react_client": f"chainlit-react-client-{client_version}.tgz",
        },
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finalize(dist: Path, build_info: Path) -> dict:
    """Check dist/ holds exactly the expected assets and write SHA256SUMS."""
    info = json.loads(build_info.read_text(encoding="utf-8"))
    found = {
        "wheel": sorted(p.name for p in dist.glob("*.whl")),
        "sdist": sorted(p.name for p in dist.glob("*.tar.gz")),
        "react_client": sorted(p.name for p in dist.glob("*.tgz")),
    }
    for kind, expected in info["files"].items():
        if found[kind] != [expected]:
            raise VersionError(
                f"Expected exactly one {kind} named {expected} in {dist}, "
                f"found: {', '.join(found[kind]) or 'nothing'}"
            )
    # Binary mode marker (" *") so the file verifies with `sha256sum -c` on
    # every platform.
    lines = [f"{sha256(dist / name)} *{name}\n" for name in info["files"].values()]
    (dist / CHECKSUMS_NAME).write_text("".join(lines), encoding="utf-8", newline="\n")
    return info


def set_output(**values: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as file:
        file.writelines(f"{name}={value}\n" for name, value in values.items())


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: %(default)s).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    stamp = commands.add_parser("stamp", help="Compute the versions of this build.")
    stamp.add_argument(
        "--write",
        action="store_true",
        help="Rewrite version.py and the react-client package.json in place.",
    )
    stamp.add_argument(
        "--build-info",
        type=Path,
        help=f"Also write the metadata to this {BUILD_INFO_NAME}.",
    )
    stamp.add_argument("--event", default=env("GITHUB_EVENT_NAME"))
    stamp.add_argument("--ref", default=env("GITHUB_REF"))
    stamp.add_argument("--sha", default=env("GITHUB_SHA"))
    stamp.add_argument("--run-id", default=env("GITHUB_RUN_ID"))
    stamp.add_argument(
        "--pr-number",
        default=env("PR_NUMBER"),
        help="Pull request number (default: $PR_NUMBER, else parsed from the ref).",
    )
    stamp.add_argument(
        "--build-number", type=int, help="Override the commit count (for tests)."
    )

    final = commands.add_parser(
        "finalize", help=f"Verify the built files and write {CHECKSUMS_NAME}."
    )
    final.add_argument("--dist", type=Path, default=Path("dist"))
    final.add_argument(
        "--build-info", type=Path, help=f"Default: <dist>/{BUILD_INFO_NAME}."
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    if args.command == "finalize":
        info = finalize(args.dist, args.build_info or args.dist / BUILD_INFO_NAME)
        print(json.dumps(info, indent=2))
        return

    sha = args.sha or git(root, "rev-parse", "HEAD") or ""
    ref = args.ref or git(root, "symbolic-ref", "--quiet", "HEAD") or ""
    info = compute(
        root,
        event=args.event or "local",
        ref=ref,
        sha=sha,
        run_id=args.run_id or None,
        pr_number=args.pr_number or None,
        number=args.build_number,
    )
    if args.write:
        write_python_version(root, info["version"])
        write_client_version(root, info["client_version"])
    if args.build_info:
        write_json(args.build_info, info)
    set_output(version=info["version"], client_version=info["client_version"])
    print(json.dumps(info, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except VersionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
