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
- New recipe kind `files`: pick files out of an upstream archive by glob and install them at fixed
  paths (gzipped man pages, shell completions), with an optional second asset via `from`.
- Architecture-independent packages (`assets.all`), listed in every `binary-<arch>` index.
- `[package]` overrides on `kind = "deb"` recipes, to fix dependencies of republished `.deb` files.
- Asset names in recipes can be globs.
- Optional `note` in a recipe (compatibility hint), stored in `index.json` and shown on the landing page.
- Redesigned landing page: hero, install steps with copy buttons, package cards, trust section and FAQ.
  One self-contained file, light and dark mode, no external requests.
- Recipes for `fzf`, `ripgrep`, `zoxide`, `yt-dlp` (zipapp) and `ghostty`.
- GitHub Actions: CI and a scheduled publish workflow.
