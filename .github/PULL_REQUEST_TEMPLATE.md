<!--
This fork does NOT accept new features. Pull requests that add functionality will be closed.

Do NOT open a public pull request for a security fix. Report the vulnerability
privately first: https://github.com/chainlit-community/chainlit/security/advisories/new
The fix is then developed in a private fork. See SECURITY.md.
-->

## What kind of change is this?

<!-- Tick exactly one. If none applies, this pull request is out of scope. -->

- [ ] Bug fix
- [ ] CI, reliability, package management or tooling improvement or simplification
- [ ] Feature reduction (removing or simplifying existing functionality)
- [ ] Documentation

## What changed and why

## Tests

<!--
Test coverage is required:
- backend changes need unit tests;
- frontend changes need E2E (Cypress) tests;
- bug fixes need a regression test that fails without the fix.
-->

## How was it verified

## Checklist

- [ ] This does not add a new feature.
- [ ] This is not a fix for an undisclosed security vulnerability.
- [ ] Backend changes are covered by unit tests, and frontend changes by E2E tests.
- [ ] A bug fix comes with a regression test.
- [ ] The change is backward compatible, or it is a feature reduction that says who is affected and how to migrate.
- [ ] User-visible changes have an entry under `## [Unreleased]` in `CHANGELOG.md` (breaking ones start with `**Breaking:**`), or a maintainer labelled this pull request `no changelog`.
