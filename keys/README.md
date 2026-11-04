# Signing key

Put the **public** key here as `rafaelvieiras-apt.asc` (ASCII armored). It is
safe to commit and is what `repo.toml` points at. The private half never enters
this repository: it lives in Bitwarden and in the `APT_GPG_PRIVATE_KEY` Actions
secret. See [docs/setup.md](../docs/setup.md).
