"""Tests for scripts/ci_version.py, the CI build version stamper."""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
from packaging.version import Version

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_version.py"
SHA = "0123456789abcdef0123456789abcdef01234567"

PACKAGE_JSON = """{
  "name": "@chainlit/react-client",
  "description": "Websocket client to connect to your chainlit app.",
  "version": "0.5.0",
  "files": [
    "dist",
    "README.md"
  ],
  "dependencies": {
    "some-package": "^1.0.0"
  },
  "nested": {
    "version": "9.9.9"
  }
}
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_version", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_version = _load_script()


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit(root: Path, message: str = "commit") -> str:
    git(root, "add", "-A")
    git(root, "commit", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD")


def set_version(root: Path, version: str) -> None:
    (root / ci_version.VERSION_FILE).write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )


def set_client_version(root: Path, version: str) -> None:
    (root / ci_version.CLIENT_PACKAGE_JSON).write_text(
        PACKAGE_JSON.replace('"version": "0.5.0"', f'"version": "{version}"'),
        encoding="utf-8",
    )


# https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
# with \d spelled out as [0-9].
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository with three commits and the two files that get stamped."""
    for name in (
        "GITHUB_OUTPUT",
        "GITHUB_EVENT_NAME",
        "GITHUB_REF",
        "GITHUB_SHA",
        "GITHUB_RUN_ID",
        "PR_NUMBER",
        "RELEASE_VERSION",
        "PUBLISH_INDEX",
    ):
        monkeypatch.delenv(name, raising=False)

    (tmp_path / ci_version.VERSION_FILE).parent.mkdir(parents=True)
    (tmp_path / ci_version.CLIENT_PACKAGE_JSON).parent.mkdir(parents=True)
    set_version(tmp_path, "3.0.0")
    (tmp_path / ci_version.CLIENT_PACKAGE_JSON).write_text(PACKAGE_JSON)
    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    for _ in range(3):
        commit(tmp_path)
    return tmp_path


def compute(repo: Path, event: str, ref: str, **kwargs) -> dict:
    return ci_version.compute(repo, event=event, ref=ref, sha=SHA, **kwargs)


def test_push_to_main(repo: Path):
    info = compute(repo, "push", "refs/heads/main", run_id="123456789")

    assert info == {
        "version": "3.0.0.dev3",
        "client_version": "0.5.0-dev.3",
        "base_version": "3.0.0",
        "build_number": 3,
        "sha": SHA,
        "ref": "refs/heads/main",
        "event": "push",
        "pr_number": None,
        "run_id": "123456789",
        "files": {
            "wheel": "chainlit_community-3.0.0.dev3-py3-none-any.whl",
            "sdist": "chainlit_community-3.0.0.dev3.tar.gz",
            "react_client": "chainlit-react-client-0.5.0-dev.3.tgz",
        },
    }


def test_build_number_counts_commits_unless_overridden(repo: Path):
    commit(repo)

    assert compute(repo, "push", "refs/heads/main")["build_number"] == 4
    assert compute(repo, "push", "refs/heads/main", number=1234)["version"] == (
        "3.0.0.dev1234"
    )


def test_pull_request(repo: Path):
    info = compute(repo, "pull_request", "refs/pull/42/merge", pr_number="42")

    assert info["version"] == "3.0.0.dev3+pr42.g0123456"
    assert info["pr_number"] == 42
    assert info["files"]["wheel"] == (
        "chainlit_community-3.0.0.dev3+pr42.g0123456-py3-none-any.whl"
    )
    assert (
        info["files"]["sdist"] == "chainlit_community-3.0.0.dev3+pr42.g0123456.tar.gz"
    )
    # npm versions carry no build label.
    assert info["client_version"] == "0.5.0-dev.3"


def test_pull_request_number_falls_back_to_the_ref(repo: Path):
    info = compute(repo, "pull_request", "refs/pull/7/merge")

    assert info["version"] == "3.0.0.dev3+pr7.g0123456"
    assert info["pr_number"] == 7


def test_pull_request_without_a_number_is_rejected(repo: Path):
    with pytest.raises(ci_version.VersionError, match="pull request number"):
        compute(repo, "pull_request", "refs/heads/feature")

    with pytest.raises(ci_version.VersionError, match="Invalid pull request number"):
        compute(repo, "pull_request", "refs/pull/7/merge", pr_number="7; rm -rf /")


def test_merge_group(repo: Path):
    ref = "refs/heads/gh-readonly-queue/main/pr-42-0123456789abcdef"
    info = compute(repo, "merge_group", ref)

    assert info["version"] == "3.0.0.dev3+mq.g0123456"
    assert info["pr_number"] is None


@pytest.mark.parametrize(
    ("event", "ref", "label"),
    [
        ("push", "refs/heads/dev", "dev"),
        ("push", "refs/heads/release/3.0", "release.3.0"),
        ("push", "refs/heads/Feature/Add_Thing--v2", "feature.add.thing.v2"),
        ("push", "refs/heads/-weird-/ünï/", "weird.n"),
        ("push", "refs/heads/fix/007", "fix.7"),
        ("workflow_dispatch", "refs/heads/main", "main"),
        ("release", "refs/tags/3.0.0", "3.0.0"),
        ("workflow_dispatch", "", "workflow.dispatch"),
        ("", "", "local"),
        ("push", "refs/heads/" + "a" * 39 + "/b", "a" * 39),
    ],
)
def test_other_refs_use_a_sanitized_label(repo: Path, event: str, ref: str, label: str):
    version = compute(repo, event, ref)["version"]

    assert version == f"3.0.0.dev3+{label}.g0123456"
    # The version is already in the normalized form build tools put in file names.
    assert str(Version(version)) == version


@pytest.mark.parametrize(
    ("event", "ref", "pr_number"),
    [
        ("push", "refs/heads/main", None),
        ("pull_request", "refs/pull/42/merge", "42"),
        ("merge_group", "refs/heads/gh-readonly-queue/main/pr-42-abc", None),
        ("push", "refs/heads/release/3.0", None),
    ],
)
def test_versions_are_valid_and_sort_between_releases(
    repo: Path, event: str, ref: str, pr_number: str | None
):
    version = Version(compute(repo, event, ref, pr_number=pr_number)["version"])

    assert version.is_devrelease
    assert Version("2.12.0") < version < Version("3.0.0")


def test_later_builds_sort_higher(repo: Path):
    first = Version(compute(repo, "push", "refs/heads/main")["version"])
    commit(repo)
    second = Version(compute(repo, "push", "refs/heads/main")["version"])

    assert first < second


BASE_VERSIONS = [
    "3.0.0",
    "3.0",
    "2.0rc0",
    "2.4.0rc0",
    "3.0.0a1",
    "3.0.0b2",
    "3.0.0rc1",
    "2.7.1.1",
    "2.7.1.1rc10",
]


@pytest.mark.parametrize("base", BASE_VERSIONS)
@pytest.mark.parametrize(
    ("event", "ref", "local"),
    [
        ("push", "refs/heads/main", ""),
        ("pull_request", "refs/pull/42/merge", "+pr42.g0123456"),
        ("merge_group", "refs/heads/gh-readonly-queue/main/pr-42-abc", "+mq.g0123456"),
    ],
)
def test_base_version_shapes(repo: Path, base: str, event: str, ref: str, local: str):
    set_version(repo, base)

    info = compute(repo, event, ref)

    version = info["version"]
    assert info["base_version"] == base
    assert version == f"{base}.dev3{local}"
    assert info["files"]["wheel"] == f"chainlit_community-{version}-py3-none-any.whl"
    assert info["files"]["sdist"] == f"chainlit_community-{version}.tar.gz"
    # Valid, and already in the normalized form build tools put in file names.
    assert str(Version(base)) == base
    assert str(Version(version)) == version
    assert Version(version).is_devrelease
    assert Version(version) < Version(base)


def test_release_candidate_builds_sort_between_releases(repo: Path):
    set_version(repo, "3.0.0rc1")
    candidate_build = compute(repo, "push", "refs/heads/main", number=1234)["version"]
    set_version(repo, "3.0.0")
    final_build = compute(repo, "push", "refs/heads/main", number=1234)["version"]

    assert (candidate_build, final_build) == ("3.0.0rc1.dev1234", "3.0.0.dev1234")
    # PEP 440 puts the dev builds of a final release *before* its pre-releases,
    # so main must carry the next rcN (not the final version) after an RC.
    assert (
        Version("2.12.0")
        < Version(final_build)
        < Version(candidate_build)
        < Version("3.0.0rc1")
        < Version("3.0.0rc2.dev1235")
        < Version("3.0.0rc2")
        < Version("3.0.0")
    )


@pytest.mark.parametrize(
    "version",
    [
        "3",
        "3.0.0.0.0",
        "v3.0.0",
        "03.0.0",
        "3.00.0",
        "3.0.0.dev5",
        "3.0.0rc1.dev5",
        "3.0.0.post1",
        "3.0.0rc1.post1",
        "3.0.0+local",
        "3.0.0rc1+local",
        "1!3.0.0",
        # Not the canonical PEP 440 spelling of a pre-release.
        "3.0.0-rc",
        "3.0.0-rc1",
        "3.0.0-rc.1",
        "3.0.0.rc1",
        "3.0.0_rc1",
        "3.0.0rc",
        "3.0.0rc01",
        "3.0.0RC1",
        "3.0.0c1",
        "3.0.0alpha1",
        "3.0.0a1b2",
        "3.0.0rc1 ",
        "3.0.0rc1\\n",
        # Digits, but not ASCII ones: Arabic-Indic and fullwidth.
        "\u0663.0.0",
        "3.0.\uff10",
        "3.0.0rc\u0661",
        "",
    ],
)
def test_other_base_versions_are_rejected(repo: Path, version: str):
    set_version(repo, version)

    with pytest.raises(ci_version.VersionError, match=r"PEP 440 form.*3\.0\.0rc1"):
        compute(repo, "push", "refs/heads/main")


@pytest.mark.parametrize(
    ("base", "stamped"),
    [
        ("0.5.0", "0.5.0-dev.3"),
        ("0.5.0-rc.1", "0.5.0-rc.1.dev.3"),
        ("0.5.0-rc", "0.5.0-rc.dev.3"),
        ("0.5.0-beta-2.x", "0.5.0-beta-2.x.dev.3"),
        ("1.0.0-0.3.7", "1.0.0-0.3.7.dev.3"),
        ("1.0.0-devel", "1.0.0-devel.dev.3"),
    ],
)
def test_client_version_shapes(repo: Path, base: str, stamped: str):
    set_client_version(repo, base)

    info = compute(repo, "pull_request", "refs/pull/42/merge")

    assert info["client_version"] == stamped
    assert info["files"]["react_client"] == f"chainlit-react-client-{stamped}.tgz"
    assert SEMVER_RE.fullmatch(base)
    assert SEMVER_RE.fullmatch(stamped)


@pytest.mark.parametrize(
    "version",
    [
        "0.5",
        "0.5.0.1",
        "v0.5.0",
        "00.5.0",
        "0.5.0-",
        "0.5.0-rc..1",
        "0.5.0-rc.01",
        "0.5.0-rc_1",
        "0.5.0-rc.1+build",
        "0.5.0+build",
        "0.5.0rc1",
        # Already stamped.
        "0.5.0-dev.3",
        "0.5.0-rc.1.dev.3",
        "0.5.0-rc.1\\n",
        "0.\u0665.0",
        "0.5.0-rc.\uff11",
        "0.5.0-\u00e9",
    ],
)
def test_other_client_versions_are_rejected(repo: Path, version: str):
    set_client_version(repo, version)

    with pytest.raises(ci_version.VersionError, match=r"package\.json.*semver"):
        compute(repo, "push", "refs/heads/main")


def test_client_version_must_be_a_string(repo: Path):
    path = repo / ci_version.CLIENT_PACKAGE_JSON
    path.write_text(PACKAGE_JSON.replace('"version": "0.5.0"', '"version": 5'))

    with pytest.raises(ci_version.VersionError, match=r"package\.json"):
        compute(repo, "push", "refs/heads/main")


@pytest.mark.parametrize("number", ["\u0664\u0662", "\uff14\uff12", "\u00b2", "4 2"])
def test_non_ascii_pull_request_number_is_rejected(repo: Path, number: str):
    with pytest.raises(ci_version.VersionError, match="Invalid pull request number"):
        compute(repo, "pull_request", "refs/heads/feature", pr_number=number)

    # Nor is such a number picked up from the ref.
    with pytest.raises(ci_version.VersionError, match="pull request number"):
        compute(repo, "pull_request", f"refs/pull/{number}/merge")


def test_invalid_sha_is_rejected(repo: Path):
    with pytest.raises(ci_version.VersionError, match="40 character"):
        ci_version.compute(repo, event="push", ref="refs/heads/main", sha="abc1234")


def test_shallow_clone_is_rejected(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
):
    shallow = tmp_path_factory.mktemp("shallow")
    git(shallow, "clone", "--quiet", "--depth", "1", repo.as_uri(), ".")

    with pytest.raises(ci_version.VersionError, match="shallow"):
        compute(shallow, "push", "refs/heads/main")
    assert compute(shallow, "push", "refs/heads/main", number=3)["build_number"] == 3


def test_tag_guard_rejects_an_unbumped_version(repo: Path):
    git(repo, "tag", "3.0.0")
    commit(repo, "work after the release")

    with pytest.raises(ci_version.VersionError, match=r"Tag 3\.0\.0 already exists"):
        compute(repo, "push", "refs/heads/main")


def test_tag_guard_handles_annotated_tags(repo: Path):
    git(repo, "tag", "--annotate", "--message", "Release 3.0.0", "3.0.0")
    commit(repo, "work after the release")

    with pytest.raises(ci_version.VersionError, match=r"Tag 3\.0\.0 already exists"):
        compute(repo, "push", "refs/heads/main")


def test_tag_guard_only_warns_outside_main(repo: Path, capsys):
    # Pull requests must keep building between a release and the version bump.
    git(repo, "tag", "3.0.0")
    commit(repo, "work after the release")

    info = compute(repo, "pull_request", "refs/pull/7/merge")

    assert info["version"].startswith("3.0.0.dev4+pr7.")
    assert "::warning::Tag 3.0.0 already exists" in capsys.readouterr().err


def test_tag_guard_allows_the_release_commit_itself(repo: Path):
    # publish.yaml runs CI on the release tag, where version.py rightly still
    # holds the version being released.
    git(repo, "tag", "--annotate", "--message", "Release 3.0.0", "3.0.0")

    info = compute(repo, "release", "refs/tags/3.0.0")

    assert info["version"] == "3.0.0.dev3+3.0.0.g0123456"


def test_tag_guard_ignores_other_tags(repo: Path):
    git(repo, "tag", "2.12.0")
    git(repo, "tag", "v3.0.0")
    git(repo, "tag", "3.0.0rc1")
    commit(repo)

    assert compute(repo, "push", "refs/heads/main")["version"] == "3.0.0.dev4"


@pytest.mark.parametrize("base", ["3.0.0rc1", "2.0rc0", "2.7.1.1"])
def test_tag_guard_covers_every_base_version_shape(repo: Path, base: str, capsys):
    set_version(repo, base)
    commit(repo, f"prepare {base}")
    git(repo, "tag", base)

    # The tagged commit itself still builds ...
    assert compute(repo, "push", "refs/heads/main")["version"] == f"{base}.dev4"

    # ... later ones only once the version is bumped.
    commit(repo, "work after the release")
    with pytest.raises(ci_version.VersionError, match="already exists"):
        compute(repo, "push", "refs/heads/main")
    assert compute(repo, "pull_request", "refs/pull/7/merge")["version"] == (
        f"{base}.dev5+pr7.g0123456"
    )
    assert f"::warning::Tag {base} already exists" in capsys.readouterr().err


def test_tag_guard_passes_once_the_version_is_bumped(repo: Path):
    git(repo, "tag", "3.0.0")
    set_version(repo, "3.0.1")
    commit(repo, "bump version")

    assert compute(repo, "push", "refs/heads/main")["version"] == "3.0.1.dev4"


def run_main(repo: Path, *args: str) -> int:
    return ci_version.main(["--root", str(repo), *args])


def test_stamp_is_a_dry_run_without_write(repo: Path, capsys: pytest.CaptureFixture):
    assert run_main(repo, "stamp", "--event", "push", "--ref", "refs/heads/main") == 0

    assert json.loads(capsys.readouterr().out)["version"] == "3.0.0.dev3"
    assert git(repo, "status", "--porcelain") == ""


def test_stamp_write_rewrites_both_files(repo: Path):
    rc = run_main(
        repo, "stamp", "--write", "--event", "pull_request", "--pr-number", "42"
    )

    assert rc == 0
    sha7 = git(repo, "rev-parse", "HEAD")[:7]
    assert (repo / ci_version.VERSION_FILE).read_text() == (
        f'__version__ = "3.0.0.dev3+pr42.g{sha7}"\n'
    )
    # Only the top-level version changes; the formatting is left alone.
    assert (repo / ci_version.CLIENT_PACKAGE_JSON).read_text() == PACKAGE_JSON.replace(
        '"version": "0.5.0"', '"version": "0.5.0-dev.3"'
    )


def test_stamp_write_handles_pre_release_bases(repo: Path):
    set_version(repo, "3.0.0rc1")
    set_client_version(repo, "0.5.0-rc.1")
    commit(repo, "release candidate")
    args = ("stamp", "--write", "--event", "push", "--ref", "refs/heads/main")

    assert run_main(repo, *args) == 0

    assert (repo / ci_version.VERSION_FILE).read_text() == (
        '__version__ = "3.0.0rc1.dev4"\n'
    )
    assert json.loads((repo / ci_version.CLIENT_PACKAGE_JSON).read_text())[
        "version"
    ] == ("0.5.0-rc.1.dev.4")
    # Both stamped files are recognised as such.
    assert run_main(repo, *args) == 1
    set_version(repo, "3.0.0rc1")
    assert run_main(repo, *args) == 1


def test_stamping_twice_is_rejected(repo: Path, capsys: pytest.CaptureFixture):
    args = ("stamp", "--write", "--event", "push", "--ref", "refs/heads/main")
    assert run_main(repo, *args) == 0

    assert run_main(repo, *args) == 1
    assert "already stamped" in capsys.readouterr().err


def test_stamp_reads_github_environment(
    repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    out = tmp_path_factory.mktemp("out")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    monkeypatch.setenv("PR_NUMBER", "42")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out / "github_output"))

    assert run_main(repo, "stamp", "--build-info", str(out / "build-info.json")) == 0

    info = json.loads((out / "build-info.json").read_text())
    assert list(info) == [
        "version",
        "client_version",
        "base_version",
        "build_number",
        "sha",
        "ref",
        "event",
        "pr_number",
        "run_id",
        "files",
    ]
    assert list(info["files"]) == ["wheel", "sdist", "react_client"]
    assert info["version"] == "3.0.0.dev3+pr42.g0123456"
    assert info["pr_number"] == 42
    assert info["run_id"] == "123456789"
    assert (out / "github_output").read_text() == (
        "version=3.0.0.dev3+pr42.g0123456\nclient_version=0.5.0-dev.3\n"
    )


def test_tag_guard_fails_the_command(repo: Path, capsys: pytest.CaptureFixture):
    git(repo, "tag", "3.0.0")
    commit(repo)

    args = ("stamp", "--write", "--event", "push", "--ref", "refs/heads/main")
    assert run_main(repo, *args) == 1
    assert "Tag 3.0.0 already exists" in capsys.readouterr().err
    assert git(repo, "status", "--porcelain") == ""


@pytest.fixture
def dist(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    dist = tmp_path_factory.mktemp("dist")
    info = compute(repo, "pull_request", "refs/pull/42/merge")
    ci_version.write_json(dist / "build-info.json", info)
    for name in info["files"].values():
        (dist / name).write_bytes(name.encode())
    return dist


def test_finalize_writes_checksums_for_the_three_assets(dist: Path):
    assert ci_version.main(["finalize", "--dist", str(dist)]) == 0

    info = json.loads((dist / "build-info.json").read_text())
    lines = (dist / "SHA256SUMS").read_text().splitlines()
    assert lines == [
        f"{hashlib.sha256(name.encode()).hexdigest()} *{name}"
        for name in info["files"].values()
    ]
    assert len(lines) == 3


@pytest.mark.parametrize("kind", ["wheel", "sdist", "react_client"])
def test_finalize_rejects_a_missing_asset(
    dist: Path, kind: str, capsys: pytest.CaptureFixture
):
    info = json.loads((dist / "build-info.json").read_text())
    (dist / info["files"][kind]).unlink()

    assert ci_version.main(["finalize", "--dist", str(dist)]) == 1
    assert f"exactly one {kind}" in capsys.readouterr().err


def test_finalize_rejects_an_unexpected_asset(
    dist: Path, capsys: pytest.CaptureFixture
):
    (dist / "chainlit_community-3.0.0-py3-none-any.whl").write_bytes(b"stale")

    assert ci_version.main(["finalize", "--dist", str(dist)]) == 1
    assert "chainlit_community-3.0.0-py3-none-any.whl" in capsys.readouterr().err


# --- Official releases -------------------------------------------------------

DISPATCH = "workflow_dispatch"
MAIN = "refs/heads/main"
CHANGELOG = """# Changelog

## [Unreleased]

### Added

- Something new.

## [2.12.0] - 2026-08-25

### Fixed

- Something old.
"""


def write_notes(
    root: Path, version: str | None = None, changelog: str = CHANGELOG
) -> None:
    """The hand-written notes a release needs; a final also gets its file."""
    if version is not None:
        changelog = changelog.replace(
            "## [Unreleased]",
            f"## [Unreleased]\n\n- Next.\n\n## [{version}] - 2026-12-01",
        )
        notes = root / ci_version.RELEASE_NOTES_DIR / f"{version}.md"
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text("# Upgrading\n\nRead this first.\n", encoding="utf-8")
    (root / ci_version.CHANGELOG_FILE).write_text(changelog, encoding="utf-8")


def release(repo: Path, version: str, index: str | None = "pypi", **kwargs) -> dict:
    kwargs.setdefault("event", DISPATCH)
    kwargs.setdefault("ref", MAIN)
    return compute(repo, release_version=version, index=index, **kwargs)


def test_distribution_name_matches_the_project_and_the_other_script():
    root = SCRIPT.parents[1]
    project = tomllib.loads((root / "backend" / "pyproject.toml").read_text("utf-8"))
    spec = importlib.util.spec_from_file_location(
        "release_notes_for_name", SCRIPT.with_name("release_notes.py")
    )
    assert spec is not None
    assert spec.loader is not None
    release_notes = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules.
    sys.modules[spec.name] = release_notes
    try:
        spec.loader.exec_module(release_notes)
    finally:
        del sys.modules[spec.name]

    assert project["project"]["name"] == ci_version.DIST_NAME == "chainlit-community"
    assert release_notes.DIST_NAME == ci_version.DIST_NAME
    assert ci_version.DIST_FILE_PREFIX == "chainlit_community"
    # The import package and the console script keep the upstream name.
    assert project["project"]["scripts"] == {"chainlit": "chainlit.cli:cli"}
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "chainlit"
    ]


@pytest.mark.parametrize("version", ["3.0.0a0", "3.0.0b2", "3.0.0rc1"])
@pytest.mark.parametrize(
    ("index", "ref"),
    [("pypi", MAIN), ("testpypi", MAIN), ("testpypi", "refs/heads/feature/x")],
)
def test_pre_release(repo: Path, version: str, index: str, ref: str):
    write_notes(repo)

    info = release(repo, version, index, ref=ref, run_id="123456789")

    assert info == {
        "version": version,
        "client_version": "0.5.0-dev.3",
        "base_version": "3.0.0",
        "build_number": 3,
        "sha": SHA,
        "ref": ref,
        "event": DISPATCH,
        "pr_number": None,
        "run_id": "123456789",
        "files": {
            "wheel": f"chainlit_community-{version}-py3-none-any.whl",
            "sdist": f"chainlit_community-{version}.tar.gz",
            "react_client": "chainlit-react-client-0.5.0-dev.3.tgz",
        },
    }
    assert str(Version(version)) == version


def test_final_release(repo: Path):
    write_notes(repo, "3.0.0")

    info = release(repo, "3.0.0")

    assert info["version"] == info["base_version"] == "3.0.0"
    assert info["files"]["wheel"] == "chainlit_community-3.0.0-py3-none-any.whl"
    assert info["files"]["sdist"] == "chainlit_community-3.0.0.tar.gz"
    # The react-client is not released this way; it is stamped as always.
    assert info["client_version"] == "0.5.0-dev.3"


@pytest.mark.parametrize(
    "version",
    [
        "3.0.0.dev1",
        "3.0.0rc1.dev1",
        "3.0.0.post1",
        "3.0.0+local",
        "1!3.0.0",
        "v3.0.0",
        "3.0.0-rc1",
        "3.0.0rc01",
        "3.0.0.rc1",
        "3.0.0RC1",
        "3.0.0c1",
        "3.0.0alpha1",
        "3.0.0rc",
        "03.0.0",
        "3",
        "3.0.0.0.0",
        "3.0.0 ",
        "3.0.0rc\u0664",
        "main",
    ],
)
def test_release_version_must_be_canonical(repo: Path, version: str):
    write_notes(repo, "3.0.0")

    with pytest.raises(ci_version.VersionError, match="not a canonical official"):
        release(repo, version)


@pytest.mark.parametrize(
    "version", ["3.0.1", "2.12.1", "3.0.1rc1", "3.1.0", "4.0.0", "3.0", "3.0.0.0"]
)
def test_release_version_must_belong_to_the_base_version(repo: Path, version: str):
    write_notes(repo, version)

    with pytest.raises(ci_version.VersionError, match=r"is not 3\.0\.0 or one of"):
        release(repo, version)


@pytest.mark.parametrize("version", ["3.0.0rc1", "3.0.0rc2", "3.0.0"])
def test_release_needs_a_final_base_version(repo: Path, version: str):
    set_version(repo, "3.0.0rc1")
    write_notes(repo, "3.0.0")

    with pytest.raises(
        ci_version.VersionError, match=r"holds the pre-release 3\.0\.0rc1"
    ):
        release(repo, version)


@pytest.mark.parametrize(
    "event", ["push", "pull_request", "release", "schedule", "workflow_run", "local"]
)
def test_release_needs_a_manual_run(repo: Path, event: str):
    write_notes(repo)

    with pytest.raises(ci_version.VersionError, match="only built by a manual run"):
        release(repo, "3.0.0rc1", "testpypi", event=event)


@pytest.mark.parametrize(
    "ref", ["refs/heads/release", "refs/heads/main2", "refs/heads/feature/main"]
)
def test_pypi_releases_only_from_main(repo: Path, ref: str):
    write_notes(repo)

    with pytest.raises(
        ci_version.VersionError, match="only built from refs/heads/main"
    ):
        release(repo, "3.0.0rc1", "pypi", ref=ref)
    assert release(repo, "3.0.0rc1", "testpypi", ref=ref)["version"] == "3.0.0rc1"


@pytest.mark.parametrize("ref", ["refs/tags/3.0.0rc1", "refs/pull/42/merge", ""])
@pytest.mark.parametrize("index", ["pypi", "testpypi"])
def test_release_needs_a_branch(repo: Path, ref: str, index: str):
    write_notes(repo)

    with pytest.raises(ci_version.VersionError, match="built from a branch"):
        release(repo, "3.0.0rc1", index, ref=ref)


def test_release_for_a_pull_request_is_rejected(repo: Path):
    write_notes(repo)

    with pytest.raises(ci_version.VersionError, match="pull request"):
        release(repo, "3.0.0rc1", "testpypi", pr_number="42")


@pytest.mark.parametrize("index", [None, "", "PyPI", "npm", "https://pypi.org"])
def test_release_needs_a_known_index(repo: Path, index: str | None):
    write_notes(repo)

    with pytest.raises(ci_version.VersionError, match="--index testpypi or pypi"):
        release(repo, "3.0.0rc1", index)


@pytest.mark.parametrize("index", ["pypi", "testpypi"])
def test_index_without_a_release_version_is_rejected(repo: Path, index: str):
    with pytest.raises(ci_version.VersionError, match="only applies to a release"):
        compute(repo, "push", MAIN, index=index)


@pytest.mark.parametrize("annotated", [False, True])
def test_release_of_an_existing_tag_is_rejected(repo: Path, annotated: bool):
    write_notes(repo)
    git(repo, "tag", *(("-a", "-m", "rc") if annotated else ()), "3.0.0rc1")
    commit(repo)

    with pytest.raises(ci_version.VersionError, match=r"Tag 3\.0\.0rc1 already exists"):
        release(repo, "3.0.0rc1")


def test_final_release_fails_once_its_tag_exists(repo: Path, capsys):
    """Stricter than the preview guard, which lets the tagged commit through."""
    write_notes(repo, "3.0.0")
    assert release(repo, "3.0.0")["version"] == "3.0.0"

    git(repo, "tag", "3.0.0")  # on HEAD itself

    assert compute(repo, "push", MAIN)["version"] == "3.0.0.dev3"
    with pytest.raises(ci_version.VersionError, match=r"Tag 3\.0\.0 already exists"):
        release(repo, "3.0.0")
    with pytest.raises(ci_version.VersionError, match="does not sort above"):
        release(repo, "3.0.0rc1")
    assert "::warning::" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("tags", "version"),
    [
        (["3.0.0rc2"], "3.0.0rc1"),
        (["3.0.0rc1"], "3.0.0b9"),
        (["3.0.0b1"], "3.0.0a5"),
        (["3.0.0a10"], "3.0.0a9"),
        (["3.0.0a1", "3.0.0rc1", "3.0.0b1"], "3.0.0b2"),
        (["3.0.0"], "3.0.0rc1"),
        (["3.0"], "3.0.0rc1"),
        (["3.0.0.0"], "3.0.0"),
    ],
)
def test_release_must_sort_above_existing_tags(repo: Path, tags: list, version: str):
    write_notes(repo, "3.0.0")
    for tag in tags:
        git(repo, "tag", tag)

    with pytest.raises(ci_version.VersionError, match="does not sort above"):
        release(repo, version)


@pytest.mark.parametrize(
    ("tags", "version"),
    [
        ([], "3.0.0a0"),
        (["3.0.0a0"], "3.0.0a1"),
        (["3.0.0a9"], "3.0.0a10"),
        (["3.0.0a9", "3.0.0b0"], "3.0.0rc0"),
        (["3.0.0rc1", "3.0.0rc2"], "3.0.0rc3"),
        (["3.0.0rc2"], "3.0.0"),
        # Previews, other releases and anything that is not a version.
        (["3.0.0.dev123", "3.0.0rc1.dev5", "3.0.0.dev9999"], "3.0.0a0"),
        (["2.12.0", "2.12.1rc1", "3.0.1", "3.1.0rc9", "4.0.0"], "3.0.0rc1"),
        (["v3.0.0", "3.0.0-rc5", "3.0.0.post1", "release-3.0.0", "3.0.0rc"], "3.0.0b1"),
    ],
)
def test_release_ignores_unrelated_tags(repo: Path, tags: list, version: str):
    write_notes(repo, "3.0.0")
    for tag in tags:
        git(repo, "tag", tag)

    assert release(repo, version)["version"] == version


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("3.0.0rc1", "3.0.0a0"),
        ("3.0.0rc1", "3.0.0rc1"),
        ("3.0.0", "3.0.0a0"),
        ("3.0.0", "3.0.0rc1"),
        ("3.0.0", "3.0.0"),
    ],
)
def test_rehearsal_is_not_bound_by_tags(repo: Path, tag: str, version: str):
    """A TestPyPI rehearsal creates no tag; only PyPI releases must go forward."""
    write_notes(repo, "3.0.0")
    git(repo, "tag", tag)
    commit(repo)

    assert release(repo, version, "testpypi")["version"] == version
    assert (
        release(repo, version, "testpypi", ref="refs/heads/rehearsal")["version"]
        == version
    )
    message = (
        rf"Tag {re.escape(version)} already exists"
        if version == tag
        else "does not sort above the existing tag"
    )
    with pytest.raises(ci_version.VersionError, match=message):
        release(repo, version, "pypi")


def test_rehearsal_keeps_every_other_rule(repo: Path):
    write_notes(repo)
    git(repo, "tag", "3.0.0rc1")

    for version, kwargs, message in (
        ("3.0.0.dev1", {}, "not a canonical official version"),
        ("3.0.1a0", {}, "is not 3.0.0 or one of its pre-releases"),
        ("3.0.0a0", {"event": "push"}, "only built by a manual run"),
        ("3.0.0a0", {"ref": "refs/tags/3.0.0rc1"}, "built from a branch"),
        ("3.0.0", {}, r"has no '## \[3\.0\.0\]' section"),
    ):
        with pytest.raises(ci_version.VersionError, match=message):
            release(repo, version, "testpypi", **kwargs)


def test_rehearsal_does_not_need_the_tag_list(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    write_notes(repo)
    real = ci_version.git
    monkeypatch.setattr(
        ci_version,
        "git",
        lambda root, *args: None if args[0] == "tag" else real(root, *args),
    )

    assert release(repo, "3.0.0a0", "testpypi")["version"] == "3.0.0a0"


def test_release_needs_git_to_list_tags(repo: Path, monkeypatch: pytest.MonkeyPatch):
    write_notes(repo)
    real = ci_version.git
    monkeypatch.setattr(
        ci_version,
        "git",
        lambda root, *args: None if args[0] == "tag" else real(root, *args),
    )

    with pytest.raises(ci_version.VersionError, match="list the git tags"):
        release(repo, "3.0.0rc1")


OFFICIAL_VERSIONS = [
    "3.0.0a0",
    "3.0.0a1",
    "3.0.0a10",
    "3.0.0b0",
    "3.0.0b2",
    "3.0.0rc0",
    "3.0.0rc1",
    "3.0.0rc10",
    "3.0.0",
    "3.0",
    "3.0.0.0",
    "3.0.1a0",
    "3.0.1",
    "3.0.0.1rc1",
    "3.0.0.1",
    "3.1rc1",
    "3.1",
    "2.12.0",
    "10.0.0b1",
    "10.0",
]


@pytest.mark.parametrize("left", OFFICIAL_VERSIONS)
@pytest.mark.parametrize("right", OFFICIAL_VERSIONS)
def test_official_sort_key_agrees_with_packaging(left: str, right: str):
    key = ci_version.official_sort_key

    assert (key(left) < key(right)) == (Version(left) < Version(right))
    assert (key(left) == key(right)) == (Version(left) == Version(right))
    assert (key(left)[0] == key(right)[0]) == (
        Version(left).base_version == Version(right).base_version
        or Version(Version(left).base_version) == Version(Version(right).base_version)
    )


@pytest.mark.parametrize("version", ["3.0.0.dev1", "v3.0.0", "3.0.0-rc1", "", "3"])
def test_official_sort_key_rejects_other_versions(version: str):
    with pytest.raises(ValueError, match="not a canonical official version"):
        ci_version.official_sort_key(version)


def test_final_release_needs_its_notes_file(repo: Path):
    write_notes(repo, "3.0.0")
    notes = repo / "docs" / "releases" / "3.0.0.md"

    notes.write_text(" \n\n", encoding="utf-8")
    with pytest.raises(
        ci_version.VersionError, match=r"docs/releases/3\.0\.0\.md is missing or empty"
    ):
        release(repo, "3.0.0")

    notes.unlink()
    (notes.parent / "3.0.0rc1.md").write_text("wrong file\n", encoding="utf-8")
    with pytest.raises(
        ci_version.VersionError, match=r"docs/releases/3\.0\.0\.md is missing or empty"
    ):
        release(repo, "3.0.0")


def test_final_release_needs_its_changelog_section(repo: Path):
    write_notes(repo, "3.0.0")
    write_notes(repo)  # back to [Unreleased]

    with pytest.raises(
        ci_version.VersionError, match=r"CHANGELOG\.md has no '## \[3\.0\.0\]' section"
    ):
        release(repo, "3.0.0")

    write_notes(
        repo, changelog="# Changelog\n\n## [3.0.0] - 2026-12-01\n\n## [2.12.0]\n"
    )
    with pytest.raises(
        ci_version.VersionError,
        match=r"'## \[3\.0\.0\]' section of CHANGELOG\.md is empty",
    ):
        release(repo, "3.0.0")


def test_final_release_refuses_a_draft_guide(repo: Path):
    write_notes(repo, "3.0.0")
    notes = repo / "docs" / "releases" / "3.0.0.md"
    marker = ci_version.DRAFT_MARKER
    assert marker == "<!-- release-notes: draft -->"
    notes.write_text(f"# Upgrading to 3.0.0\n\n{marker}\n\nRead this.\n", "utf-8")

    for index in ("pypi", "testpypi"):
        with pytest.raises(ci_version.VersionError) as error:
            release(repo, "3.0.0", index)
        message = str(error.value)
        assert "docs/releases/3.0.0.md is still marked as a draft" in message
        assert f"remove the '{marker}' line" in message
        assert "Verify the upgrade guide" in message
    # Pre-releases do not use the guide.
    assert release(repo, "3.0.0rc1")["version"] == "3.0.0rc1"

    # Indentation and line endings do not hide the marker.
    notes.write_bytes(f"# Upgrading\r\n\r\n  {marker}  \r\n".encode())
    with pytest.raises(ci_version.VersionError, match="still marked as a draft"):
        release(repo, "3.0.0")

    # Only a line of its own counts: prose may mention the marker.
    notes.write_text(f"# Upgrading\n\nThe `{marker}` line is gone.\n", "utf-8")
    assert release(repo, "3.0.0")["version"] == "3.0.0"


def test_pre_release_needs_changes(repo: Path):
    with pytest.raises(ci_version.VersionError, match=r"CHANGELOG\.md is missing"):
        release(repo, "3.0.0rc1")

    for changelog in (
        # Neither section.
        "# Changelog\n\n## [2.12.0]\n\n- x\n",
        # [Unreleased] empty, no section of the release.
        "# Changelog\n\n## [Unreleased]\n\n## [2.12.0]\n\n- x\n",
        # Both empty.
        "# Changelog\n\n## [Unreleased]\n\n## [3.0.0] - 2026-12-01\n\n## [2.12.0]\n",
        # The section of another release does not count.
        "# Changelog\n\n## [Unreleased]\n\n## [3.0.1] - 2026-12-01\n\n- x\n",
    ):
        write_notes(repo, changelog=changelog)
        with pytest.raises(ci_version.VersionError) as error:
            release(repo, "3.0.0rc1")
        message = str(error.value)
        assert "CHANGELOG.md has no changes for 3.0.0rc1" in message
        assert "'## [Unreleased]' section is missing or empty" in message
        assert "so is its '## [3.0.0]' section" in message

    # A pre-release needs no notes file.
    write_notes(repo)
    assert release(repo, "3.0.0rc1")["version"] == "3.0.0rc1"


@pytest.mark.parametrize(
    "changelog",
    [
        "# Changelog\n\n## [Unreleased]\n\n## [3.0.0] - 2026-12-01\n\n- x\n",
        "# Changelog\n\n## [3.0.0] - 2026-12-01\n\n- x\n\n## [2.12.0]\n\n- y\n",
    ],
    ids=["empty-unreleased", "no-unreleased"],
)
@pytest.mark.parametrize("version", ["3.0.0a0", "3.0.0rc3"])
def test_pre_release_after_the_release_pr(repo: Path, changelog: str, version: str):
    """The release PR empties [Unreleased]; an rc must still be buildable."""
    write_notes(repo, changelog=changelog)

    assert release(repo, version)["version"] == version


def test_release_changelog():
    choose = ci_version.release_changelog
    both = "## [Unreleased]\n\n- New.\n\n## [3.0.0] - 2026-12-01\n\n- Final.\n"
    moved = "## [Unreleased]\n\n## [3.0.0] - 2026-12-01\n\n- Final.\n"

    assert choose(both, "3.0.0rc1", "3.0.0") == ("Unreleased", "- New.")
    assert choose(moved, "3.0.0rc1", "3.0.0") == ("3.0.0", "- Final.")
    assert choose(both, "3.0.0", "3.0.0") == ("3.0.0", "- Final.")
    # A final never falls back to [Unreleased].
    assert choose("## [Unreleased]\n\n- New.\n", "3.0.0", "3.0.0") is None
    assert choose("## [Unreleased]\n\n## [3.0.0]\n", "3.0.0rc1", "3.0.0") is None
    assert choose(moved, "3.0.1rc1", "3.0.1") is None
    assert choose("", "3.0.0rc1", "3.0.0") is None


def test_changelog_section():
    text = """# Changelog

## [Unreleased]

### Added

- New.

```md
## [1.0.0] not a heading
```

~~~
## neither
```
~~~

## [3.0.0] - 2026-12-01

- Final.

## [3.0.0rc1]
## [2.12.0] - 2026-08-25
- Old.
"""
    section = ci_version.changelog_section

    assert section(text, "Unreleased") == (
        "### Added\n\n- New.\n\n```md\n## [1.0.0] not a heading\n```\n\n"
        "~~~\n## neither\n```\n~~~"
    )
    assert section(text, "3.0.0") == "- Final."
    assert section(text, "3.0.0rc1") == ""
    assert section(text, "2.12.0") == "- Old."
    assert section(text, "1.0.0") is None
    assert section(text, "3.0") is None
    assert section(text, "3.0.0rc") is None
    assert section(text, "3x0x0") is None
    assert section("## [3.0.0]extra\n- x\n", "3.0.0") is None
    assert section("### [3.0.0]\n- x\n", "3.0.0") is None
    assert section("", "Unreleased") is None


def test_release_stamp_command(
    repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    write_notes(repo)
    commit(repo)
    out = tmp_path_factory.mktemp("out")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out / "github_output"))
    args = ("stamp", "--write", "--event", DISPATCH, "--ref", MAIN, "--sha", SHA)

    code = run_main(
        repo,
        *args,
        "--build-info",
        str(out / "build-info.json"),
        "--release-version",
        "3.0.0rc1",
        "--index",
        "pypi",
    )

    assert code == 0
    info = json.loads((out / "build-info.json").read_text())
    assert list(info) == [
        "version",
        "client_version",
        "base_version",
        "build_number",
        "sha",
        "ref",
        "event",
        "pr_number",
        "run_id",
        "files",
    ]
    assert (info["version"], info["event"], info["ref"]) == ("3.0.0rc1", DISPATCH, MAIN)
    assert info["pr_number"] is None
    assert (repo / ci_version.VERSION_FILE).read_text() == '__version__ = "3.0.0rc1"\n'
    assert (
        '"version": "0.5.0-dev.4"'
        in (repo / ci_version.CLIENT_PACKAGE_JSON).read_text()
    )
    assert (out / "github_output").read_text() == (
        "version=3.0.0rc1\nclient_version=0.5.0-dev.4\n"
    )


def test_release_stamp_reads_the_environment(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    write_notes(repo)
    monkeypatch.setenv("GITHUB_EVENT_NAME", DISPATCH)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/rehearsal")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("RELEASE_VERSION", "3.0.0b1")
    monkeypatch.setenv("PUBLISH_INDEX", "testpypi")

    assert run_main(repo, "stamp") == 0
    assert json.loads(capsys.readouterr().out)["version"] == "3.0.0b1"

    monkeypatch.setenv("PUBLISH_INDEX", "pypi")
    assert run_main(repo, "stamp") == 1
    assert "only built from refs/heads/main" in capsys.readouterr().err


def test_empty_release_environment_is_a_normal_build(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    args = ("stamp", "--event", "push", "--ref", MAIN, "--sha", SHA)
    assert run_main(repo, *args) == 0
    expected = capsys.readouterr().out

    monkeypatch.setenv("RELEASE_VERSION", "")
    monkeypatch.setenv("PUBLISH_INDEX", "")
    assert run_main(repo, *args) == 0
    assert capsys.readouterr().out == expected
    assert json.loads(expected)["version"] == "3.0.0.dev3"

    monkeypatch.setenv("PUBLISH_INDEX", "pypi")
    assert run_main(repo, *args) == 1
    assert "only applies to a release" in capsys.readouterr().err


def test_rejected_release_does_not_write(repo: Path, capsys: pytest.CaptureFixture):
    write_notes(repo)
    commit(repo)

    code = run_main(
        repo,
        "stamp",
        "--write",
        "--event",
        "push",
        "--ref",
        MAIN,
        "--release-version",
        "3.0.0rc1",
        "--index",
        "pypi",
    )

    assert code == 1
    assert "only built by a manual run" in capsys.readouterr().err
    assert git(repo, "status", "--porcelain") == ""


def test_script_runs_isolated():
    """Standalone and standard library only: `python3 -I` must be enough."""
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "stamp", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--release-version" in result.stdout
