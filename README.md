<p align="center">
  <strong>A tiny, static, signed apt repository for developer tools that Debian and Ubuntu ship late or not at all.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
</p>

---

## Use it

```bash
sudo install -d -m 0755 /etc/apt/keyrings
sudo curl -fsSL https://apt.rafaelvieiras.com/key.gpg -o /etc/apt/keyrings/rafaelvieiras-apt.gpg
sudo tee /etc/apt/sources.list.d/rafaelvieiras-apt.sources >/dev/null <<'EOF'
Types: deb
URIs: https://apt.rafaelvieiras.com/
Suites: stable
Components: main
Signed-By: /etc/apt/keyrings/rafaelvieiras-apt.gpg
EOF
sudo apt update && sudo apt install neovim yazi
```

One suite (`stable`) serves every Debian and Ubuntu release, because the packages
are static or only need an old glibc. Architectures: `amd64`, `arm64`.
The catalogue is also published as [`index.json`](https://apt.rafaelvieiras.com/index.json).

| Package | Source | How |
|---|---|---|
| `neovim` | [neovim/neovim](https://github.com/neovim/neovim) | upstream tarball wrapped into a `.deb` |
| `yazi` | [sxyazi/yazi](https://github.com/sxyazi/yazi) | upstream static (musl) `.deb`, republished untouched |

## How it works

```
upstream GitHub release ──► aptrepo (GitHub Actions, every 6 h) ──► Cloudflare R2 ──► apt.rafaelvieiras.com
        (the source)          check, license gate, build,            static files       (Cloudflare CDN)
                              index, sign
```

- **No servers.** The repository is plain files in an R2 bucket. `apt` only needs
  HTTPS `GET`, so there is nothing to run, patch or scale.
- **Nearly free at any traffic.** R2 has no egress fees. Packages and `by-hash`
  indexes are immutable (`Cache-Control: immutable`, one year); the few mutable
  files (`InRelease`, `Packages*`, `index.json`) cache for five minutes at the
  edge. Most requests never reach R2.
- **Nothing stored on GitHub.** Binaries live only in R2. GitHub holds recipes and code.
- **State is `index.json`.** A publish reads that one file, never lists the bucket.
- **Safe to publish while clients update.** `.deb` and `by-hash` files go up first,
  the signed `InRelease` last, so no signed index ever points at a missing file.
- **Fails closed.** Unknown licence, missing asset, checksum mismatch or a signing key
  that does not match the published public key stops the run. A failing package
  never blocks the others, but the run still goes red.
- **Never goes backwards.** A retracted or re-tagged upstream release cannot
  downgrade a published package.

## Adding a package

A package is one TOML file in [`packages/`](packages/). See
[docs/adding-a-package.md](docs/adding-a-package.md).

## Setting it up

Key, bucket, domain and secrets: [docs/setup.md](docs/setup.md).

## Develop

```bash
python -m aptrepo check                      # validate recipes + licences, offline
python -m unittest discover -s tests -t .    # needs gpg and dpkg-deb
python -m aptrepo plan --storage r2          # what would be published
python -m aptrepo publish --storage dir:/tmp/bucket --config repo.toml   # local dry run
```

Python 3.11+, standard library only. External tools: `gpg`, `dpkg-deb`, and the
`aws` CLI (R2 uploads only).

## License

[MIT](LICENSE). Packaged software keeps its own licence, shipped in
`/usr/share/doc/<package>/copyright`.
