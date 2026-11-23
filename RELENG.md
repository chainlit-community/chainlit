# Release Engineering Instructions

This document outlines the steps for maintainers to create a new release of the project.

## Prerequisites

- You must have maintainer permissions on the repo to create a new release.

## Steps

1. **Determine the new version number**:
   - We use semantic versioning (major.minor.patch).
   - Increment the major version for breaking changes, minor version for new features, patch version for bug fixes only.
   - If unsure, discuss with the maintainers to determine if it should be a major/minor version bump or new patch version.

2. **Check the package version**:
   - `main` carries the version of the _next_ release (see [Preview builds](#preview-builds)), so `version` in `backend/chainlit/version.py` should normally already be the version you are about to release. Update it only if step 1 came out differently, e.g. a breaking change was merged since the last bump.
   - Update `version` in `libs/*/package.json` if there were any changes in the corresponding directories.

3. **Update the changelog**:
   - Create a pull request to update the CHANGELOG.md file with the changes for the new release.
   - Mark any breaking changes clearly.
   - Get the changelog update PR reviewed and merged.

4. **Create a new release**:
   - In the GitHub repo, go to the "Releases" page and click "Draft a new release".
   - Input the new version number as the tag (e.g. 4.0.4).
   - Use the "Generate release notes" button to auto-populate the release notes from the changelog.
   - Review the release notes, make any needed edits for clarity.
   - If this is a full release after an RC, remove any "-rc" suffix from the version number.
   - Publish the release.

5. **Update any associated documentation and examples**:
   - If needed, create PRs to update the version referenced in the docs and example code to match the newly released version.
   - Especially important for documented breaking changes.

6. **Bump `main` to the next version**:
   - Straight after publishing, open a PR that sets `version` in `backend/chainlit/version.py` to the next release version (e.g. 3.0.1 after releasing 3.0.0).
   - This is required, not optional: the CI build refuses to run while a git tag equal to the version in `version.py` exists. See [Preview builds](#preview-builds).

## RC (Release Candidate) Releases

- We create RC releases to allow testing before a full stable release
- Append "-rc" to the version number (e.g. 4.0.4-rc)
- Normally only bug fixes, no new features, between an RC and the final release version

## Preview builds

Preview builds are automatic and need no maintainer action. They are separate from the release process above and do not publish to PyPI or npm.

**One build per CI run.** `.github/workflows/build.yaml` (called from `ci.yaml`) builds the wheel and sdist and packs `@chainlit/react-client`, then uploads one workflow artifact named `dist`:

- `chainlit-<version>-py3-none-any.whl`
- `chainlit-<version>.tar.gz`
- `chainlit-react-client-<client-version>.tgz`
- `SHA256SUMS`
- `build-info.json`

The E2E tests install that wheel instead of building their own, so they test the files that ship.

**Versioning.** `backend/chainlit/version.py` on `main` holds the version of the next release. `scripts/ci_version.py` stamps the build version in CI only; nothing is committed. `N` is the commit count (`git rev-list --count HEAD`).

| Build        | Version                            | Example                       |
| ------------ | ---------------------------------- | ----------------------------- |
| `main`       | `<base>.dev<N>`                    | `3.0.0.dev1234`               |
| Pull request | `<base>.dev<N>+pr<number>.g<sha7>` | `3.0.0.dev1234+pr56.gabc1234` |
| react-client | `<package.json version>-dev.<N>`   | `0.5.0-dev.1234`              |

Under PEP 440, `3.0.0.dev1234` sorts above `2.12.0` and below `3.0.0`, so a preview build is never mistaken for the release it precedes.

**Pull requests.** When CI finishes on a pull request, `.github/workflows/pr-build-comment.yaml` posts (or updates) one comment on the PR with the build version and the commands to download the `dist` artifact and install the wheel. Workflow artifacts need a GitHub login to download, and they expire.

**`main`.** When CI succeeds on a push to `main`, `.github/workflows/preview-release.yaml` publishes a GitHub pre-release:

- The tag is the bare version (e.g. `3.0.0.dev1234`). It is never marked "Latest".
- Assets: the wheel, the sdist, the react-client tarball and `SHA256SUMS`, with build provenance attestations.
- The release notes contain the install commands for that build.

To verify a download:

```sh
sha256sum --ignore-missing -c SHA256SUMS
gh attestation verify chainlit-<version>-py3-none-any.whl -R chainlit-community/chainlit
```

**Re-running.** If the preview release for a commit failed or needs to be redone, run `.github/workflows/preview-release.yaml` manually (`workflow_dispatch`) and pass the `run_id` of the CI run whose build you want to publish.

Ping @dokterbob or @willydouhard for any questions or issues with the release process. Happy releasing!
