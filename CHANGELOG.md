# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `setup.sh`: a POSIX `sh` installer served at `/setup.sh`. It verifies the signing key (fingerprint
  with `gpg`, checksum without), writes the keyring and the DEB822 source, and refreshes
  only that source. It never installs a package. Supports `--dry-run`, `--no-update` and
  `--uninstall`, and is idempotent. Tests keep its pinned values in step with `repo.toml` and `keys/`.
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
- Landing site rebuilt with Astro (`site/`): a Home page and a compact Packages page with a live filter
  and per-package copy buttons. Static output, zero client framework, no external requests, light and
  dark mode, works without JavaScript.
- `python -m aptrepo site-data | upload-site | publish-site`: export `site-data.json` from `index.json`,
  and upload the built site. `/packages` is stored extensionless as well, so no extra Cloudflare rule is
  needed; the uploader refuses apt paths and sample-data builds.
- `publish.yml` builds and uploads the site after the packages, and also when a push touches `site/**`
  (new `force_site` input). `ci.yml` builds the site against sample data.
- Explicit content types and cache policy for site files (`_astro/` is immutable).
- Recipes for `fzf`, `ripgrep`, `zoxide`, `yt-dlp` (zipapp) and `ghostty`.
- GitHub Actions: CI and a scheduled publish workflow.

### Removed

- The Python HTML renderer (`aptrepo.site.render`); `aptrepo publish` no longer uploads `index.html`.

### Fixed

- The landing page footer showed an empty "Generated" time. The site export always sets a real UTC timestamp.
