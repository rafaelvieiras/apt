# AGENTS.md

Guidance for AI coding agents (and humans who like precise instructions) working
in this repository. This is the machine-readable companion to
[CONTRIBUTING.md](CONTRIBUTING.md); when they overlap, the commands here are
canonical.

## What this is

A static apt repository builder. Recipes in `packages/*.toml` → `aptrepo`
(Python, standard library only) → Cloudflare R2 → `apt.rafaelvieiras.com`.

```
aptrepo/
  recipe.py     TOML recipe parsing and validation
  upstream.py   GitHub release lookup and checksummed download
  licenses.py   redistribution allowlist (fails closed)
  debbuild.py   tarball -> .deb, adopt upstream .deb, companion packages
  debversion.py Debian version ordering (verified against dpkg)
  repo.py       index.json state, Packages/Release/by-hash rendering
  sign.py       GnuPG signing in a throw-away keyring
  storage.py    DirStorage (tests) and R2Storage (aws CLI), cache policy
  publish.py    orchestration and upload order
  site.py       static landing page
  cli.py        python -m aptrepo {check,plan,publish}
packages/       one recipe per upstream project
repo.toml       repository identity
keys/           PUBLIC key only
tests/          offline tests
```

## Build / run / test

```bash
python -m aptrepo check
python -m unittest discover -s tests -t . -v
python -m aptrepo publish --storage dir:/tmp/bucket --config repo.toml --dry-run
```

Run one test: `python -m unittest tests.test_aptrepo.PublishFlow.test_never_goes_backwards`.

## Rules that must not be broken

- **Never commit or print a private key, passphrase or R2 credential.** Secrets
  come from environment variables only and never go on a command line.
- **Upload order is load-bearing** (see `publish.py`): `.deb` and `by-hash` first,
  `InRelease` and `Release.gpg` last. Do not reorder.
- **Cache policy lives in `storage.cache_control`.** `pool/` and `by-hash/` are
  immutable; everything else is short. A new file type must be classified there.
- **Licence gate fails closed.** Add an SPDX id to `licenses.ALLOWED` only after
  checking that it permits redistribution.
- **Do not store binaries in git or GitHub Releases.** R2 only.
- **Reproducible builds.** Keep `SOURCE_DATE_EPOCH`, sorted file order and
  normalised mtimes; `test_tarball_deb_is_valid_and_reproducible` guards this.
- `index.json` schema changes need a `SCHEMA` bump and a migration in `load_state`.

## Language & conventions

- **Everything in this repository is in English**: code, comments, docs, commits.
- **Commits:** Conventional Commits, in English — `feat(publish): ...`,
  `fix(sign): ...`, `docs: ...`, `chore: ...`.
- Standard library only. A new dependency needs a strong reason.
- Pin GitHub Actions to a full commit SHA with a `# vX.Y.Z` comment.
- Before declaring a change done, run the unit tests **and** an install in a clean
  container (see `docs/setup.md`, "Verify"): `apt` is the real test.
