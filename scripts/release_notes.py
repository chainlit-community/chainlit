#!/usr/bin/env python3
"""Render Markdown for preview releases and PR build comments.

Reads the ``build-info.json`` produced by ``.github/workflows/build.yaml`` and
writes Markdown to stdout:

* ``release``    - body of the GitHub pre-release that publishes a ``main`` build.
* ``pr-comment`` - body of the sticky pull request comment that points at the
  ``dist`` artifact of a CI run.
* ``validate``   - no Markdown; prints the validated fields as ``key=value``
  lines (suitable for ``$GITHUB_OUTPUT``).

Security: for pull request runs ``build-info.json`` is written by code from the
pull request (possibly a fork) and is therefore attacker-controlled, while this
script runs in a privileged ``workflow_run`` job. Every field is validated
against a strict pattern before use and nothing that failed validation is ever
echoed, neither to stdout nor in error messages.

Standard library only; requires Python >= 3.11.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

MARKER = "<!-- chainlit-build-artifact -->"
ARTIFACT_NAME = "dist"
DOWNLOAD_DIR = "chainlit-dist"
MAX_BUILD_INFO_BYTES = 64 * 1024

RELEASE = "release"
PR = "pr"

# Every pattern is used with fullmatch() and spells out [0-9]: \d would also
# match non-ASCII digits. The version shapes are those scripts/ci_version.py
# accepts and produces.
_NUMBER = r"(?:0|[1-9][0-9]{0,5})"
# Canonical PEP 440: two to four release components and an optional aN / bN /
# rcN pre-release (3.0.0, 2.0rc0, 3.0.0rc1, 2.7.1.1).
_BASE_VERSION_RE = re.compile(
    rf"{_NUMBER}(?:\.{_NUMBER}){{1,3}}(?:(?:a|b|rc){_NUMBER})?"
)
# semver: X.Y.Z-dev.<N>, or X.Y.Z-<prerelease>.dev.<N> for a pre-release base,
# with optional build metadata.
_SEMVER_IDENTIFIER = rf"(?:{_NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_CLIENT_VERSION_RE = re.compile(
    rf"{_NUMBER}(?:\.{_NUMBER}){{2}}"
    rf"-(?:(?P<prerelease>{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER}){{0,7}})\.)?"
    r"dev\.(?P<build_number>[1-9][0-9]{0,9})"
    r"(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+){0,7})?"
)
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RUN_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
_REPO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
_PR_LOCAL_RE = re.compile(r"pr([1-9][0-9]{0,9})\.g([0-9a-f]{7})")
_MAX_VERSION_LENGTH = 80
_MAX_INT = 10**10

CONCLUSIONS = (
    "success",
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
)


class ValidationError(ValueError):
    """Raised when build-info.json or an argument fails validation.

    Messages must never contain the offending value.
    """


@dataclass(frozen=True)
class BuildInfo:
    version: str
    client_version: str
    base_version: str
    build_number: int
    sha: str
    ref: str
    event: str
    pr_number: int | None
    run_id: str
    wheel: str
    sdist: str
    react_client: str

    @property
    def kind(self) -> str:
        return RELEASE if self.pr_number is None else PR


def _string(data: dict, key: str, pattern: re.Pattern[str] | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or len(value) > 256:
        raise ValidationError(f"build-info: '{key}' must be a short string")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValidationError(f"build-info: '{key}' has an unexpected format")
    return value


def _integer(value: object, name: str) -> int:
    # bool is a subclass of int; reject it explicitly.
    if type(value) is not int or not 0 < value < _MAX_INT:
        raise ValidationError(f"build-info: '{name}' must be a positive integer")
    return value


def parse_build_info(data: object) -> BuildInfo:
    """Validate the decoded build-info.json and return its trusted form."""
    if not isinstance(data, dict):
        raise ValidationError("build-info: top level must be an object")

    base_version = _string(data, "base_version", _BASE_VERSION_RE)
    build_number = _integer(data.get("build_number"), "build_number")
    sha = _string(data, "sha", _SHA_RE)
    run_id = _string(data, "run_id", _RUN_ID_RE)
    client_version = _string(data, "client_version", _CLIENT_VERSION_RE)
    client = _CLIENT_VERSION_RE.fullmatch(client_version)
    # A base that already has a "dev" identifier is a tree stamped twice.
    if (
        client is None
        or int(client["build_number"]) != build_number
        or "dev" in (client["prerelease"] or "").split(".")
    ):
        raise ValidationError(
            "build-info: 'client_version' must be the react-client version + "
            "'-dev.' (or '.dev.' after a pre-release) + build_number"
        )
    ref = _string(data, "ref")
    event = _string(data, "event")

    pr_number = data.get("pr_number")
    if pr_number is not None:
        pr_number = _integer(pr_number, "pr_number")

    # The version is rebuilt from validated parts instead of being
    # pattern-matched on its own, so it cannot disagree with them.
    version = _string(data, "version")
    dev_version = f"{base_version}.dev{build_number}"
    if pr_number is None:
        if version != dev_version:
            raise ValidationError(
                "build-info: 'version' must be base_version + '.dev' + build_number"
            )
        if event != "push" or ref != "refs/heads/main":
            raise ValidationError(
                "build-info: a build without 'pr_number' must be a push to main"
            )
        if "+" in client_version:
            raise ValidationError(
                "build-info: 'client_version' must not carry build metadata"
            )
    else:
        local = version.removeprefix(f"{dev_version}+")
        match = _PR_LOCAL_RE.fullmatch(local)
        if (
            local == version
            or not match
            or int(match[1]) != pr_number
            or match[2] != sha[:7]
        ):
            raise ValidationError(
                "build-info: 'version' must be base_version + '.dev' + "
                "build_number + '+pr' + pr_number + '.g' + sha[:7]"
            )
        if event != "pull_request":
            raise ValidationError(
                "build-info: a build with 'pr_number' must be a pull_request build"
            )
    if len(version) > _MAX_VERSION_LENGTH or len(client_version) > _MAX_VERSION_LENGTH:
        raise ValidationError("build-info: version is too long")

    files = data.get("files")
    if not isinstance(files, dict):
        raise ValidationError("build-info: 'files' must be an object")
    # File names are derived from the validated versions; anything else
    # (path separators, Markdown/HTML metacharacters, ...) cannot match.
    expected = {
        "wheel": {f"chainlit-{version}-py3-none-any.whl"},
        "sdist": {f"chainlit-{version}.tar.gz"},
        # `npm pack` / `pnpm pack` may drop semver build metadata.
        "react_client": {
            f"chainlit-react-client-{client_version}.tgz",
            f"chainlit-react-client-{client_version.partition('+')[0]}.tgz",
        },
    }
    if set(files) != set(expected):
        raise ValidationError(
            "build-info: 'files' must have exactly wheel, sdist and react_client"
        )
    for key, allowed in expected.items():
        if not isinstance(files[key], str) or files[key] not in allowed:
            raise ValidationError(
                f"build-info: files.{key} does not match the build version"
            )

    return BuildInfo(
        version=version,
        client_version=client_version,
        base_version=base_version,
        build_number=build_number,
        sha=sha,
        ref=ref,
        event=event,
        pr_number=pr_number,
        run_id=run_id,
        wheel=files["wheel"],
        sdist=files["sdist"],
        react_client=files["react_client"],
    )


def load_build_info(path: Path) -> BuildInfo:
    try:
        with path.open("rb") as file:
            raw = file.read(MAX_BUILD_INFO_BYTES + 1)
    except OSError as exc:
        raise ValidationError("build-info: file cannot be read") from exc
    if len(raw) > MAX_BUILD_INFO_BYTES:
        raise ValidationError("build-info: file is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ValidationError("build-info: file is not valid UTF-8 JSON") from exc
    return parse_build_info(data)


def check_repo(repo: str) -> str:
    if not _REPO_RE.fullmatch(repo) or repo.endswith(("/.", "/..")):
        raise ValidationError("--repo must look like 'owner/name'")
    return repo


def check_expectations(
    info: BuildInfo,
    *,
    kind: str | None = None,
    expect_sha: str | None = None,
    expect_run_id: str | None = None,
    expect_pr: int | None = None,
) -> None:
    if kind is not None and info.kind != kind:
        raise ValidationError(f"build-info: not a '{kind}' build")
    if expect_sha is not None and info.sha != expect_sha:
        raise ValidationError("build-info: 'sha' does not match --expect-sha")
    if expect_run_id is not None and info.run_id != expect_run_id:
        raise ValidationError("build-info: 'run_id' does not match --expect-run-id")
    if expect_pr is not None and info.pr_number != expect_pr:
        raise ValidationError("build-info: 'pr_number' does not match --expect-pr")


def release_asset_url(repo: str, tag: str, filename: str) -> str:
    return (
        f"https://github.com/{repo}/releases/download/"
        f"{quote(tag, safe='')}/{quote(filename, safe='')}"
    )


def render_release(info: BuildInfo, repo: str) -> str:
    check_repo(repo)
    check_expectations(info, kind=RELEASE)
    tag = info.version
    wheel_url = release_asset_url(repo, tag, info.wheel)
    client_url = release_asset_url(repo, tag, info.react_client)
    commit_url = f"https://github.com/{repo}/commit/{info.sha}"
    return f"""\
> [!IMPORTANT]
> This is an **automated preview build** of `main` at commit [`{info.sha[:7]}`]({commit_url}), not an official release. It is published for every change that passes CI and may be replaced by a newer build at any time.
>
> `pip install chainlit` installs the **unmaintained upstream package** from PyPI, not this fork. To get the fixes from this repository, install from the URLs below.

## Install

### Python package (`chainlit` {info.version})

The wheel bundles the built frontend and copilot, so Node.js and pnpm are **not** needed to install it. The commands below are alternatives: use the **one** command that matches your tooling.

```bash
# pip
pip install {wheel_url}

# uv, in a project: records the dependency in pyproject.toml
uv add "chainlit @ {wheel_url}"

# uv, without a project: installs into the active virtual environment only
uv pip install {wheel_url}

# poetry
poetry add {wheel_url}
```

### `@chainlit/react-client` ({info.client_version})

Again, use the one command that matches your package manager.

```bash
# npm
npm install --allow-remote=root {client_url}

# pnpm
pnpm add {client_url}
```

npm 12 and later refuse tarball URLs outside the registry by default (`EALLOWREMOTE`), hence `--allow-remote=root`; alternatively set `allow-remote=root` in your project's `.npmrc`. Older npm versions and pnpm do not need it.

## Verify

Checksums of the assets are in `SHA256SUMS`, and each asset has a [build provenance attestation](https://github.com/{repo}/attestations):

```bash
gh release download {tag} -R {repo}
sha256sum --ignore-missing -c SHA256SUMS
gh attestation verify {info.wheel} -R {repo}
```
"""


def render_pr_comment(
    info: BuildInfo,
    repo: str,
    conclusion: str,
    *,
    artifact_url: str | None = None,
    head_sha: str | None = None,
) -> str:
    check_repo(repo)
    check_expectations(info, kind=PR)
    if conclusion not in CONCLUSIONS:
        raise ValidationError("--conclusion is not a known workflow run conclusion")
    sha = info.sha if head_sha is None else head_sha
    if not _SHA_RE.fullmatch(sha):
        raise ValidationError("--head-sha must be a full lowercase commit SHA")
    run_url = f"https://github.com/{repo}/actions/runs/{info.run_id}"
    if artifact_url is not None and not re.fullmatch(
        re.escape(run_url) + r"/artifacts/[1-9][0-9]{0,19}", artifact_url
    ):
        raise ValidationError("--artifact-url is not an artifact of this run")

    passed = conclusion == "success"
    status = "passed" if passed else f"**{conclusion.replace('_', ' ')}**"
    artifact = f"[`{ARTIFACT_NAME}` of run {info.run_id}]({run_url}#artifacts)"
    if artifact_url is not None:
        artifact += f" ([direct download]({artifact_url}))"
    warning = (
        ""
        if passed
        else f"""
> [!WARNING]
> This build comes from a CI run whose checks did **not** all pass (conclusion: `{conclusion}`). It may be broken.
"""
    )
    wheel = f"./{DOWNLOAD_DIR}/{info.wheel}"
    client = f"./{DOWNLOAD_DIR}/{info.react_client}"
    return f"""\
{MARKER}

## Build artifacts for this pull request

|          |     |
| -------- | --- |
| Version  | `{info.version}` |
| Commit   | [`{sha[:7]}`](https://github.com/{repo}/commit/{sha}) |
| CI       | {status} |
| Artifact | {artifact} |
{warning}
> [!CAUTION]
> These packages are built from the **unreviewed code of this pull request**. Only install them if you trust the changes.

Downloading workflow artifacts requires being signed in to GitHub, and artifacts **expire** (they are deleted after the repository's retention period).

### Install

First download the artifact with the GitHub CLI (signed in):

```bash
gh run download {info.run_id} -R {repo} -n {ARTIFACT_NAME} -D {DOWNLOAD_DIR}
```

Then install the Python package. The commands are alternatives: use the **one** command that matches your tooling. The wheel bundles the built frontend, so Node.js and pnpm are not needed.

```bash
# pip
pip install {wheel}

# uv, in a project: records the dependency in pyproject.toml
uv add {wheel}

# uv, without a project: installs into the active virtual environment only
uv pip install {wheel}

# poetry
poetry add {wheel}
```

For `@chainlit/react-client` ({info.client_version}), again use the one command that matches your package manager:

```bash
# npm
npm install {client}

# pnpm
pnpm add {client}
```

`sha256sum -c SHA256SUMS` inside `{DOWNLOAD_DIR}` checks the downloaded files.

<sub>Updated automatically for the latest commit of this pull request.</sub>
"""


def render_outputs(info: BuildInfo) -> str:
    """Validated fields as key=value lines; every value is a safe token."""
    fields = {
        "kind": info.kind,
        "version": info.version,
        "client_version": info.client_version,
        "base_version": info.base_version,
        "build_number": info.build_number,
        "sha": info.sha,
        "run_id": info.run_id,
        "pr_number": "" if info.pr_number is None else info.pr_number,
        "wheel": info.wheel,
        "sdist": info.sdist,
        "react_client": info.react_client,
    }
    return "".join(f"{key}={value}\n" for key, value in fields.items())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("build_info", type=Path, help="path to build-info.json")
        sub.add_argument("--expect-sha", help="build-info 'sha' must equal this")
        sub.add_argument("--expect-run-id", help="build-info 'run_id' must equal this")
        sub.add_argument(
            "--expect-pr", type=int, help="build-info 'pr_number' must equal this"
        )

    release = commands.add_parser(RELEASE, help="body of a preview pre-release")
    add_common(release)
    release.add_argument("--repo", required=True, help="owner/name")

    comment = commands.add_parser("pr-comment", help="body of the sticky PR comment")
    add_common(comment)
    comment.add_argument("--repo", required=True, help="owner/name")
    comment.add_argument(
        "--conclusion", required=True, help="conclusion of the CI workflow run"
    )
    comment.add_argument("--artifact-url", help="direct URL of the dist artifact")
    comment.add_argument(
        "--head-sha",
        help="trusted PR head commit to show instead of the build-info 'sha'",
    )

    validate = commands.add_parser("validate", help="print validated fields")
    add_common(validate)
    validate.add_argument("--kind", choices=(RELEASE, PR), help="required build kind")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        info = load_build_info(args.build_info)
        check_expectations(
            info,
            expect_sha=args.expect_sha,
            expect_run_id=args.expect_run_id,
            expect_pr=args.expect_pr,
        )
        if args.command == RELEASE:
            output = render_release(info, args.repo)
        elif args.command == "pr-comment":
            output = render_pr_comment(
                info,
                args.repo,
                args.conclusion,
                artifact_url=args.artifact_url,
                head_sha=args.head_sha,
            )
        else:
            check_expectations(info, kind=args.kind)
            output = render_outputs(info)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
