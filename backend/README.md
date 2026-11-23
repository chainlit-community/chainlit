<h1 align="center">Welcome to Chainlit 👋</h1>

<p align="center">
<b>Build python production-ready conversational AI applications in minutes, not weeks ⚡️</b>

</p>
<p align="center">
    <a href="https://github.com/chainlit-community/chainlit/graphs/contributors" rel="nofollow"><img alt="Contributors" src="https://img.shields.io/github/contributors/chainlit-community/chainlit" style="max-width:100%;"></a>
    <a href="https://github.com/chainlit-community/chainlit/actions/workflows/ci.yaml" rel="nofollow"><img alt="CI" src="https://github.com/chainlit-community/chainlit/actions/workflows/ci.yaml/badge.svg" style="max-width:100%;"></a>
    <a href="https://opencollective.com/chainlit" rel="nofollow"><img alt="Backers on Open Collective" src="https://opencollective.com/chainlit/backers/badge.svg" style="max-width:100%;"></a>
    <!-- Re-enable once we have actual sponsors
    <a href="https://opencollective.com/chainlit" rel="nofollow"><img alt="Sponsors on Open Collective" src="https://opencollective.com/chainlit/sponsors/badge.svg" style="max-width:100%;"></a>
    -->
</p>

> ⚠️ **Notice:** this is the community-maintained fork of Chainlit.
>
> The original repository, [Chainlit/chainlit](https://github.com/Chainlit/chainlit), has been archived by its owners. Maintenance continues here, in [chainlit-community/chainlit](https://github.com/chainlit-community/chainlit).
>
> This fork is not affiliated with, maintained by or endorsed by Chainlit SAS, which provides no warranties on it.
>
> **Scope:** we fix security issues and bugs, and we remove functionality so that it can be plugged in by others later. We do not add features.

<p align="center">
    <a href="https://docs.chainlit.io"><b>Documentation</b></a>  •  
    <a href="https://github.com/Chainlit/cookbook"><b>Cookbook</b></a>  •  
    <a href="https://opencollective.com/chainlit"><b>Open Collective</b></a>
</p>

The documentation and cookbook linked above are those of the original Chainlit. They are not maintained by this fork and may be outdated. We intend to bring the documentation into this repository, so that it is always updated in sync with the code. The Discord and Twitter account linked from this page also belong to the original project.

https://github.com/user-attachments/assets/b3738aba-55c0-42fa-ac00-6efd1ee0d148

## Installation

This fork is published on PyPI as [`chainlit-community`](https://pypi.org/project/chainlit-community/). Only the name of the distribution is different: you still `import chainlit` in Python and run the `chainlit` command.

Use the one command that matches your tooling:

```sh
# pip
pip install chainlit-community

# uv, in a project: records the dependency in pyproject.toml
uv add chainlit-community

# uv, without a project: installs into the active virtual environment only
uv pip install chainlit-community

# poetry
poetry add chainlit-community
```

Extras go on the new name as well, e.g. `pip install "chainlit-community[custom-data]"`.

> ⚠️ **Warning:** if the original `chainlit` distribution is installed, uninstall it first (`pip uninstall chainlit`). `chainlit` and `chainlit-community` both provide the `chainlit` import package, so when both are installed they overwrite each other's files.
>
> `pip install chainlit` still installs the last release of the original project from PyPI. That package is unmaintained and does not receive the security fixes made in this fork. For security reasons, we strongly recommend that you do not install it. A third-party package that depends on `chainlit` will pull it in alongside `chainlit-community`; `pip show chainlit` tells you whether it is installed and what requires it.

The [PyPI project page](https://pypi.org/project/chainlit-community/#history) and the [Releases page](https://github.com/chainlit-community/chainlit/releases) show which versions have been published. To install a release candidate, pin it exactly, e.g. `pip install chainlit-community==3.0.0rc1`. If the version you need has not been published yet, use a preview build.

Coming from the original `chainlit`? Each final release has an [upgrade guide](https://github.com/chainlit-community/chainlit/tree/main/docs/releases).

Then check that it works:

```sh
chainlit hello
```

If this opens the `hello app` in your browser, you're all set!

### Preview builds

Every commit on `main` that passes CI is published as a pre-release on [GitHub Releases](https://github.com/chainlit-community/chainlit/releases), with a version such as `3.0.0.dev1234`. Preview builds are not published to PyPI. Pick one from the Releases page and install its wheel by URL, replacing `<version>`. Use the one command that matches your tooling:

```sh
# pip
pip install https://github.com/chainlit-community/chainlit/releases/download/<version>/chainlit_community-<version>-py3-none-any.whl

# uv, in a project: records the dependency in pyproject.toml
uv add "chainlit-community @ https://github.com/chainlit-community/chainlit/releases/download/<version>/chainlit_community-<version>-py3-none-any.whl"

# uv, without a project: installs into the active virtual environment only
uv pip install https://github.com/chainlit-community/chainlit/releases/download/<version>/chainlit_community-<version>-py3-none-any.whl

# poetry
poetry add https://github.com/chainlit-community/chainlit/releases/download/<version>/chainlit_community-<version>-py3-none-any.whl
```

The notes of each release have these commands with the version filled in, plus how to verify the download against `SHA256SUMS` and its build provenance attestation. The wheel includes the built frontend, so Node and pnpm are not needed.

### From source

To install the current state of `main` (or another branch) straight from GitHub:

```sh
pip install git+https://github.com/chainlit-community/chainlit.git#subdirectory=backend/
```

(Requires Node and pnpm installed on the system.)

## 🚀 Quickstart

### 🐍 Pure Python

Create a new file `demo.py` with the following code:

```python
import chainlit as cl


@cl.step(type="tool")
async def tool():
    # Fake tool
    await cl.sleep(2)
    return "Response from the tool!"


@cl.on_message  # this function will be called every time a user inputs a message in the UI
async def main(message: cl.Message):
    """
    This function is called every time a user inputs a message in the UI.
    It sends back an intermediate response from the tool, followed by the final answer.

    Args:
        message: The user's message.

    Returns:
        None.
    """


    # Call the tool
    tool_res = await tool()

    await cl.Message(content=tool_res).send()
```

Now run it!

```sh
chainlit run demo.py -w
```

<img src="/images/quick-start.png" alt="Quick Start"></img>

## 📚 More Examples - Cookbook

You can find various examples of Chainlit apps [here](https://github.com/Chainlit/cookbook) that leverage tools and services such as OpenAI, Anthropiс, LangChain, LlamaIndex, ChromaDB, Pinecone and more.

## 🛠 Maintenance and governance

The primary maintainer of this fork is Mathijs de Bruin ([@dokterbob](https://github.com/dokterbob), <mathijs@mathijsfietst.nl>), who was one of the maintainers of the original Chainlit.

The fork is run and supported by enterprise users who have compliance and security needs, and by [Open Collective](https://opencollective.com/chainlit) sponsors.

We are explicitly open to additional maintainers. To keep the supply chain secure, we ask that maintainers:

- have a track record of quality contributions, here or on the original project;
- can verify their identity;
- have stable contact details (email).

## 💖 Sponsoring

You can support the maintenance of this fork through the [Chainlit Open Collective](https://opencollective.com/chainlit).

We are open to discussing how to fairly share any income from the Open Collective amongst maintainers.

## 💁 Contributing

We currently do not accept contributions that add new features. We welcome bug fixes (including CI, reliability, package management and tooling improvements and simplifications) and feature reductions, such as removing legacy functionality.

For what we accept and how to contribute, see [here](/CONTRIBUTING.md).

Security fixes are handled privately: report vulnerabilities through the [security policy](/SECURITY.md), never in a public issue or pull request.

## 📃 License

Chainlit is open-source and licensed under the [Apache 2.0](LICENSE) license.
