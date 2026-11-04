# Contributing to rafaelvieiras/apt

Thanks for your interest! For a terse, machine-readable command reference (handy
for AI coding agents too), see [AGENTS.md](AGENTS.md).

## Request a package

Open an issue with the upstream repository, its licence, and where it publishes
binaries. Good candidates are tools with a GitHub release, a licence that allows
redistribution, and no up-to-date package in Debian or Ubuntu.

## Add one yourself

Follow [docs/adding-a-package.md](docs/adding-a-package.md) and open a PR. CI runs
the recipe check and the unit tests.

## Conventions

- **Language.** Code, comments, docs and commits are in **English**.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(recipe): ...`, `fix(publish): ...`, `docs: ...`.
- Standard library only for the tooling.

## Reporting issues

- **Bugs and package requests:** open an issue.
- **Security vulnerabilities:** please do **not** open a public issue. See
  [SECURITY.md](SECURITY.md).
