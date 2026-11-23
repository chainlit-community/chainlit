# Release Engineering Instructions

This document is the runbook for maintainers who publish a version of the project.

There are two kinds of builds:

- **Official versions** (`3.0.0`, `3.0.0rc1`) are published by hand to [PyPI](https://pypi.org/project/chainlit-community/) as `chainlit-community`, with a GitHub release. The rest of this document is about these.
- **[Preview builds](#preview-builds)** (`3.0.0.dev1234`) are published automatically to GitHub Releases for every commit on `main`. They need no maintainer action.

## How publishing works

The distribution is called `chainlit-community`. The import package (`chainlit`) and the command (`chainlit`) keep their names.

Everything goes through one workflow, `.github/workflows/publish.yaml`, which is only ever started by hand:

- GitHub: **Actions → Publish → Run workflow**, or
- CLI: `gh workflow run publish.yaml -f version=<V> -f index=<testpypi|pypi>`

| Input     | Value                                                                          |
| --------- | ------------------------------------------------------------------------------ |
| `version` | The version to publish, typed in full (see [Versions](#versions)).             |
| `index`   | `testpypi` (default) for a rehearsal, `pypi` for the real thing (`main` only). |

The run is titled "Publish `<version>` to `<index>`". It does the following, in order:

1. Checks the version and the branch, and that the release notes exist (see [Release notes](#release-notes)). This happens in the stamp step of the build job, about a minute into the run, after the dependencies are installed. If a check fails, nothing is built or uploaded; the lint, type-check and unit-test jobs run in parallel and still run to the end.
2. Builds the wheel, the sdist and the `@chainlit/react-client` tarball with the version stamped at build time. Nothing is committed.
3. Runs the full CI, including the E2E tests, on exactly the files that will be uploaded.
4. Uploads the wheel and the sdist with PyPI trusted publishing. There are no API tokens. The upload job runs in the GitHub environment `pypi` or `testpypi`; the required reviewers of the `pypi` environment are the approval gate, so a run for PyPI waits there until a reviewer approves it.
5. For `index=pypi` only: creates a **draft** GitHub release on the built commit, with the wheel, the sdist, the react-client tarball and `SHA256SUMS` attached, and build provenance attested. A maintainer reviews the notes and clicks **Publish release**; that creates the tag, which is the bare version (e.g. `3.0.0`). Alphas, betas and release candidates are marked as pre-release.

A TestPyPI run stops after step 4: no tag, no release.

### Versions

- We use semantic versioning (major.minor.patch): major for breaking changes, patch for bug fixes only. If unsure, discuss with the other maintainers.
- `version` in `backend/chainlit/version.py` on `main` always holds the next **final** version, e.g. `3.0.0`. It never holds a pre-release.
- The version you type must be that version, or an alpha, beta or release candidate of it in PEP 440 form: `3.0.0a0`, `3.0.0b1`, `3.0.0rc1` (not `3.0.0-rc1`). `.dev` versions are refused; those are preview builds.
- For `index=pypi`, it must not already be tagged, and it must be higher than every official version of that release published before it (`3.0.0rc2` after `3.0.0rc1`, never the other way round). A TestPyPI rehearsal is not bound by the tags.
- `index=pypi` is only allowed from `main`. A TestPyPI rehearsal may run from any branch. Publishing from `release/**` backport branches is not supported yet.

### Release notes

- **Pre-release** (alpha, beta, RC): generated from the `[Unreleased]` section of `CHANGELOG.md`, followed by the install and verify instructions. Edit them in the draft if needed. If `[Unreleased]` is empty because the release PR has already moved its entries (e.g. `3.0.0rc3` after the CI of the final failed), the `[<V>]` section of the final version is used instead. The workflow refuses a pre-release if both are missing or empty.
- **Final**: written beforehand, in a release PR (see [Publish a final release](#publish-a-final-release)). The body of the draft is the upgrade guide `docs/releases/<V>.md`, then the `[<V>]` section of `CHANGELOG.md`, then the install and verify instructions. The workflow refuses a final version if either the guide or the changelog section is missing, or if the guide still contains the draft marker, a line `<!-- release-notes: draft -->`. Removing that line is the maintainer's sign-off on the guide; see [docs/releases/README.md](docs/releases/README.md#the-draft-marker).

## Publish a pre-release

Pre-releases need no commits and no pull request. Between an RC and the final version, normally only bug fixes are merged.

1. Pick the next pre-release of the version in `version.py`, e.g. `3.0.0rc1`.
2. Optional: [rehearse on TestPyPI](#rehearse-on-testpypi) first.
3. On `main`, run the workflow: `gh workflow run publish.yaml -f version=3.0.0rc1 -f index=pypi`.
4. When CI has passed, the run waits for the `pypi` environment. A required reviewer approves it; the files are then uploaded to PyPI.
5. Open the draft on the [Releases page](https://github.com/chainlit-community/chainlit/releases), check that it is marked as pre-release, edit the notes if needed and click **Publish release**.
6. [Verify](#verify-a-published-release) the published version.

## Publish a final release

1. **Open the release PR.** It contains:
   - `CHANGELOG.md`: the entries of `[Unreleased]` moved into a new `## [<V>] - <date>` section, breaking changes marked clearly. Leave an empty `## [Unreleased]` heading in place. First check `git log <previous version>..HEAD` for user-visible changes that have no entry yet.
   - `docs/releases/<V>.md`: the upgrade guide. An AI agent drafts it from the changelog and the commits since the last final release; a maintainer verifies it and removes the draft marker. See [docs/releases/README.md](docs/releases/README.md) for the required structure and the checklist.
   - If the version in `version.py` is not the one you are releasing (e.g. a breaking change was merged since the last bump), the corrected version.
   - `version` in `libs/*/package.json`, if those packages changed and the version was not bumped yet.
2. **Get the release PR reviewed and merged.**
3. **Run the workflow** on `main`: `gh workflow run publish.yaml -f version=<V> -f index=pypi`.
4. **Approve the upload.** When CI has passed, the run waits for the `pypi` environment. Once a required reviewer approves, the version is on PyPI and cannot be changed.
5. **Review the draft release.** Read the notes as rendered, fix what needs fixing and click **Publish release**. This creates the tag. Until then, `main` keeps producing `<V>.devN` preview builds, so publish the draft promptly and then merge the bump PR.
6. **[Verify](#verify-a-published-release)** the published version.
7. **Open the bump PR straight away.** Set `version` in `backend/chainlit/version.py` to the next version (e.g. `3.0.1` after `3.0.0`). This is required, not optional: while a tag equal to the version in `version.py` exists, builds of `main` fail, so no preview build is published (pull request builds only warn).
8. If needed, open PRs to update the version referenced in documentation and example code.

## Rehearse on TestPyPI

A rehearsal runs everything up to and including the upload, against [test.pypi.org](https://test.pypi.org/project/chainlit-community/). It needs no approval and may run from any branch, which makes it the way to test changes to the workflow itself.

1. Pick a throwaway alpha that will never be published for real, e.g. `3.0.0a0`. Rehearsals are not bound by the existing tags, so `3.0.0a0` stays valid after `3.0.0rc1` has been released. But each version can be uploaded to TestPyPI only once: every rehearsal uses up its version, so the next one needs `3.0.0a1`, and so on.
2. Run the workflow: `gh workflow run publish.yaml --ref <branch> -f version=3.0.0a0 -f index=testpypi`.
3. Check the result in a fresh virtual environment. TestPyPI does not have the dependencies, so those come from PyPI:

   ```sh
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ chainlit-community==3.0.0a0
   chainlit --version
   ```

## Verify a published release

In a fresh virtual environment, replacing `<V>`:

```sh
pip install chainlit-community==<V>
chainlit --version
```

Then check the files of the GitHub release against their checksums and their build provenance:

```sh
gh release download <V> -R chainlit-community/chainlit
sha256sum --ignore-missing -c SHA256SUMS
gh attestation verify chainlit_community-<V>-py3-none-any.whl -R chainlit-community/chainlit
```

To check that PyPI serves the same wheel, download it into the same directory and run the checksum again:

```sh
pip download --no-deps chainlit-community==<V>
sha256sum --ignore-missing -c SHA256SUMS
```

## Recovery

A version uploaded to PyPI or TestPyPI can never be uploaded again, not even after deleting it. Everything below follows from that.

| What happened                                                         | What to do                                                                                                                                                                            |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A check or CI failed before the upload                                | Fix the cause and run the workflow again with the same version.                                                                                                                       |
| A flaky job failed                                                    | Use **Re-run failed jobs**. Never use **Re-run all jobs** once an upload has happened: it would build different files under a version that already exists.                            |
| The upload succeeded, the release job failed                          | Use **Re-run failed jobs**.                                                                                                                                                           |
| The version is burned (partial or incorrect upload)                   | Yank it on PyPI and publish the next one: the next `rcN` for a pre-release, the next patch version for a final (which needs its own bump of `version.py` and its own release PR).     |
| The draft release is wrong, but the files on PyPI are fine            | Edit the draft; nothing needs to be rebuilt.                                                                                                                                          |
| The same version was run again before its draft release was published | The tag does not exist yet, so the version check passes and the full CI runs; the index then rejects the duplicate upload. Nothing is harmed. Publish the existing draft instead.     |
| The `pypi` approval came more than 14 days after the build            | The upload job fails when it downloads the build, because the artifact has expired. Nothing was uploaded, so the version is not burned: run the workflow again with the same version. |

## One-time setup

This is already in place, except where marked. It is listed so that it can be checked or redone.

| Where               | What                                                                                                                                                                       |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GitHub environments | `pypi`: required reviewers, deployment branch `main`. `testpypi`: no reviewers, any branch.                                                                                |
| pypi.org            | Trusted publisher: project `chainlit-community`, owner `chainlit-community`, repository `chainlit`, workflow `publish.yaml`, environment `pypi`. **To be registered.**     |
| test.pypi.org       | Trusted publisher: project `chainlit-community`, owner `chainlit-community`, repository `chainlit`, workflow `publish.yaml`, environment `testpypi`. **To be registered.** |

Until the first upload, the trusted publisher is a _pending_ publisher. A pending publisher does not reserve the project name: if someone else registers `chainlit-community` first, the pending publisher stops working.

`@chainlit/react-client` is not published to npm by this fork yet. `.github/workflows/publish-libs.yaml` is inert until that is set up; for now the package is distributed as a tarball attached to GitHub releases.

## Preview builds

Preview builds are automatic and need no maintainer action. They are separate from the release process above and are not published to PyPI or npm.

**One build per CI run.** `.github/workflows/build.yaml` (called from `ci.yaml`) builds the wheel and sdist and packs `@chainlit/react-client`, then uploads one workflow artifact named `dist`:

- `chainlit_community-<version>-py3-none-any.whl`
- `chainlit_community-<version>.tar.gz`
- `chainlit-react-client-<client-version>.tgz`
- `SHA256SUMS`
- `build-info.json`

The E2E tests install that wheel instead of building their own, so they test the files that ship.

**Versioning.** `backend/chainlit/version.py` on `main` holds the next final version. `scripts/ci_version.py` stamps the build version in CI only; nothing is committed. `N` is the commit count (`git rev-list --count HEAD`).

| Build        | Version                            | Example                       |
| ------------ | ---------------------------------- | ----------------------------- |
| `main`       | `<base>.dev<N>`                    | `3.0.0.dev1234`               |
| Pull request | `<base>.dev<N>+pr<number>.g<sha7>` | `3.0.0.dev1234+pr56.gabc1234` |
| react-client | `<package.json version>-dev.<N>`   | `0.6.0-dev.1234`              |

Under PEP 440, `3.0.0.dev1234` sorts above `2.12.0` and below `3.0.0`, so a preview build is never mistaken for the release it precedes.

It also sorts below `3.0.0rc1`, so a preview build made after a release candidate has a lower version than that candidate. This is harmless: preview builds are only ever installed by URL, never resolved by version.

If the react-client `package.json` holds a pre-release, `.dev.<N>` is appended instead, e.g. `0.6.0-rc.1.dev.1234`.

**Pull requests.** When CI finishes on a pull request, `.github/workflows/pr-build-comment.yaml` posts (or updates) one comment on the PR with the build version and the commands to download the `dist` artifact and install the wheel. Workflow artifacts need a GitHub login to download, and they expire.

**`main`.** When CI succeeds on a push to `main`, `.github/workflows/preview-release.yaml` publishes a GitHub pre-release:

- The tag is the bare version (e.g. `3.0.0.dev1234`). It is never marked "Latest".
- Assets: the wheel, the sdist, the react-client tarball and `SHA256SUMS`, with build provenance attestations.
- The release notes contain the install commands for that build.

To verify a download:

```sh
sha256sum --ignore-missing -c SHA256SUMS
gh attestation verify chainlit_community-<version>-py3-none-any.whl -R chainlit-community/chainlit
```

**Re-running.** If the preview release for a commit failed or needs to be redone, run `.github/workflows/preview-release.yaml` manually (`workflow_dispatch`) and pass the `run_id` of the CI run whose build you want to publish.

Ping @dokterbob or @willydouhard for any questions or issues with the release process. Happy releasing!
