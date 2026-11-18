# Release Engineering Instructions

This document outlines the steps for maintainers to create a new release of this fork.

## Prerequisites

- You must have maintainer permissions on the repo to create a new release.

## Distribution

Releases are published as GitHub Releases, built and uploaded by `.github/workflows/release.yaml` when a release tag is pushed. This fork does not publish to PyPI or npm: `publish.yaml` (PyPI) and `publish-libs.yaml` (npm) are kept only as manual, `workflow_dispatch`-only workflows and are not part of the release flow.

## Steps

1. **Determine the new version number**:
   - Versions follow [PEP 440](https://peps.python.org/pep-0440/), tagged bare (no `v` prefix), e.g. `2.12.1`.
   - Release candidates use the `rcN` suffix, e.g. `2.12.1rc1` — not the old `-rc` suffix.
   - If unsure whether a change warrants a major/minor/patch bump, discuss with the maintainers first.

2. **Bump the package version**:
   - Update `version` in `backend/chainlit/version.py`. This must match the tag exactly — the `validate` job in `release.yaml` fails the release otherwise.
   - If `libs/react-client/` changed since the last release, also bump `version` in `libs/react-client/package.json`. That version is independent of the Chainlit release tag and is what ships in the asset's file name.

3. **Update the changelog**:
   - Open a pull request moving the relevant entries out of the `[Unreleased]` section of `CHANGELOG.md` into a new version section.
   - Mark any breaking changes clearly.
   - Get the changelog PR reviewed and merged to `main`.

4. **Tag the release**:
   - Tag the merged commit on `main` with the bare version and push the tag:
     ```sh
     git tag <version> <main-commit>
     git push community <version>
     ```
   - Pushing the tag triggers `release.yaml`:
     - `validate` fails the run unless the tag matches `__version__` in `backend/chainlit/version.py` exactly and the tagged commit is on `main`.
     - Full CI (`ci.yaml`, including E2E on Ubuntu and Windows) runs before `build`.
     - `build` produces `chainlit-<version>-py3-none-any.whl`, `chainlit-<version>.tar.gz`, `chainlit-react-client-<client-version>.tgz`, and `SHA256SUMS` in `dist/`.
     - `release` attests build provenance for every asset, creates a draft release with generated notes and the assets, then publishes it.
   - A PEP 440 pre-release version (e.g. `2.12.1rc1`) is published as a GitHub pre-release and is not marked "Latest".

## Dry run

To build and validate without tagging or publishing anything, run the workflow manually from any ref:

- Actions → Release → Run workflow, or
- `gh workflow run release.yaml --ref <ref>`

This runs the full build and uploads the result as a workflow artifact named `release-dist`. It creates no release.

## Verifying a release

```sh
# in a fresh virtualenv
pip install https://github.com/chainlit-community/chainlit/releases/download/<version>/chainlit-<version>-py3-none-any.whl
chainlit --version

# asset integrity
sha256sum -c SHA256SUMS

# build provenance
gh attestation verify chainlit-<version>-py3-none-any.whl -R chainlit-community/chainlit
```

## When CI flakes

E2E has known flaky specs, especially on Windows. Re-run the failed job(s) rather than the whole workflow, and log each occurrence as a comment on [issue #10](https://github.com/chainlit-community/chainlit/issues/10).

## Recovery

If a run fails before the `release` job publishes anything:

- Delete the draft release, if one was created.
- Delete the tag, locally and on the remote:
  ```sh
  git tag -d <version>
  git push community :refs/tags/<version>
  ```
- Fix the issue on `main`, then re-tag.

Never re-use a version that was already published, even if the release is later deleted — cut a new version instead.

## RC (Release Candidate) Releases

- RC releases allow testing before a full stable release.
- Use the PEP 440 suffix `rcN`, e.g. `2.12.1rc1`.
- Normally only bug fixes, no new features, between an RC and the final release version.

Questions or issues with the release process? Ping the maintainers (see the main [README](/README.md)). Happy releasing!
