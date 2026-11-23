"""Tests for the `chainlit` command line."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import chainlit
from chainlit.version import __version__

# Run in a child process: importing chainlit.cli calls nest_asyncio.apply() and
# logging.basicConfig(), which must not leak into the rest of the test session.
VERSION_OPTION_SCRIPT = textwrap.dedent(
    """
    import importlib.metadata

    from click.testing import CliRunner

    from chainlit.cli import cli


    def no_metadata(*args, **kwargs):
        raise AssertionError("the version must not come from distribution metadata")


    # After the imports (dependencies read their own metadata at import time);
    # click resolves the version when the option is used.
    importlib.metadata.version = no_metadata
    importlib.metadata.distribution = no_metadata
    importlib.metadata.packages_distributions = no_metadata

    result = CliRunner().invoke(cli, ["--version"])
    if result.exception is not None:
        raise result.exception
    print(repr(result.output))
    raise SystemExit(result.exit_code)
    """
)


def test_version_option_prints_the_package_version(tmp_path: Path):
    """The distribution is chainlit-community, not chainlit: click must not look
    the version up by the name of the import package."""
    # The child must import the same chainlit as this process, installed or not.
    package_parent = str(Path(chainlit.__file__).resolve().parents[1])
    python_path = os.pathsep.join(
        filter(None, [package_parent, os.environ.get("PYTHONPATH")])
    )

    result = subprocess.run(
        [sys.executable, "-c", VERSION_OPTION_SCRIPT],
        cwd=tmp_path,  # chainlit writes its default config to the working directory
        env={**os.environ, "PYTHONPATH": python_path},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == repr(f"Chainlit, version {__version__}\n")
