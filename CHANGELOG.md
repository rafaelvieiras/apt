# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `aptrepo`: recipe parser, licence gate, `.deb` builder, index renderer with
  `by-hash`, GnuPG signing, directory and Cloudflare R2 storage, static landing page.
- Recipes for `neovim` (wrapped upstream tarball) and `yazi` (upstream musl `.deb`).
- Transitional `neovim-runtime` so `apt upgrade` moves Debian/Ubuntu installs over cleanly.
- GitHub Actions: CI and a scheduled publish workflow.
