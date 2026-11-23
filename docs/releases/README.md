# Upgrade guides

This directory holds one upgrade guide per final release: `docs/releases/<version>.md`, e.g. [`3.0.0.md`](3.0.0.md). Pre-releases (alphas, betas, release candidates) do not get one.

A guide tells someone running the previous release what they have to **do** to move to this one. It is not a second changelog: [CHANGELOG.md](../../CHANGELOG.md) lists what changed, the guide explains the consequences and the steps.

The guide is part of the release:

- It is added in the release PR, together with the changelog section of that version (see [RELENG.md](../../RELENG.md#publish-a-final-release)).
- The publish workflow refuses a final version whose `docs/releases/<version>.md` is missing.
- It becomes the first part of the notes of the GitHub release, followed by the changelog section and the install and verify instructions.

## Structure

Use these sections, in this order. Write "None." under a heading that has nothing, rather than leaving it out.

1. **Title**: `# Upgrading to <version>`, followed by one line saying which version the guide upgrades from.
2. **Who should upgrade, and why**: who is affected and what they gain, security fixes first.
3. **Before you upgrade**: what must be true before installing, such as supported Python versions and changes to how the package is installed, with the exact commands.
4. **Breaking changes**: one subsection per change, each with the same three parts:
   - **What changed**: the exact names (modules, classes, settings, environment variables).
   - **Who is affected**: how readers can tell whether this applies to them.
   - **What to do**: the migration steps, as commands or code where possible.
5. **Other notable changes**: changes that need no action but that people may notice. Keep it short and link to the changelog for the rest.
6. **Verify the install**: commands that show the upgrade worked.

Removed features and package renames are breaking changes: give them their own subsection, even when the changelog lists them under another heading.

## An agent drafts, a human verifies

The first draft is written by an AI agent, from:

- the changelog section of the version (`[Unreleased]` until the release PR renames it);
- the commits since the last final release (`git log <previous version>..HEAD`), including the bodies of the commit messages;
- the code itself, for exact names and behaviour.

The agent marks the draft as such at the top, and ends it with a section **Unverified / needs maintainer confirmation** that lists every statement it could not trace to the code or the changelog.

A maintainer then verifies the draft. The release PR is not ready to merge until every box is ticked:

- [ ] Every breaking change in the changelog section of this version is covered by a subsection of the guide.
- [ ] Every breaking change in the commits since the last final release (`!` in the subject or `BREAKING CHANGE:` in the body) is in the changelog and in the guide.
- [ ] Each migration step was tried, or traced to the code that makes it necessary.
- [ ] Every name, command, version number and date in the guide has a source in this repository. Claims without one are removed.
- [ ] Every item of the "Unverified" list is either confirmed and moved into the guide, or deleted.
- [ ] The draft notice at the top and the "Unverified" section are removed.
- [ ] The install commands were run against the published files (a release candidate or a TestPyPI rehearsal), not just read.
