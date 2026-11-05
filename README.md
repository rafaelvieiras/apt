<p align="center">
  <strong>A tiny, static, signed apt repository for developer tools that Debian and Ubuntu ship late or not at all.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
</p>

---

## Use it

The short way. [`setup.sh`](site/public/setup.sh) adds the key and the source and checks the key
fingerprint. It never installs a package:

```bash
curl -fsSL https://apt.rafaelvieiras.com/setup.sh | sudo sh                    # add the repository
curl -fsSL https://apt.rafaelvieiras.com/setup.sh | sudo sh -s -- --uninstall  # remove it again
sudo apt install neovim yazi                                                   # then use apt as usual
```

Add `--dry-run` to see every step without changing anything, or download the file and read it first.
By hand, the script is the key and source commands below; the last line is yours to run:

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
sudo apt update && sudo apt install neovim yazi   # or any package from the table below
```

One suite (`stable`) serves every Debian and Ubuntu release, because the packages
are static or only need an old glibc. Architectures: `amd64`, `arm64`.
The landing page and the full package list are at <https://apt.rafaelvieiras.com> and
<https://apt.rafaelvieiras.com/packages>. The catalogue is also published as
[`index.json`](https://apt.rafaelvieiras.com/index.json).

| Package | Source | How |
|---|---|---|
| `neovim` | [neovim/neovim](https://github.com/neovim/neovim) | upstream tarball wrapped into a `.deb` |
| `yazi` | [sxyazi/yazi](https://github.com/sxyazi/yazi) | upstream static (musl) `.deb`, republished untouched |
| `fzf` | [junegunn/fzf](https://github.com/junegunn/fzf) | upstream binary wrapped into a `.deb` |
| `ripgrep` | [BurntSushi/ripgrep](https://github.com/BurntSushi/ripgrep) | upstream static (musl) build, man page and completions |
| `zoxide` | [ajeetdsouza/zoxide](https://github.com/ajeetdsouza/zoxide) | upstream static (musl) build, man pages and completions |
| `yt-dlp` | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | upstream zipapp, runs on the system `python3` (>= 3.11); architecture `all` |
| `ghostty` | [ghostty-org/ghostty](https://ghostty.org) | community `.deb` from [mkasberg/ghostty-ubuntu](https://github.com/mkasberg/ghostty-ubuntu) (Ghostty ships no Linux binaries); needs glibc >= 2.38: Ubuntu 24.04+, Debian 13+ |

Some packages need a newer system than others. `apt` refuses to install a package it cannot satisfy
(`yt-dlp` on Ubuntu 22.04, `ghostty` on Debian 12 and Ubuntu 22.04) and leaves the rest alone.

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

### Landing site

The site in [`site/`](site/) is a static [Astro](https://astro.build) project: two pages (Home and
Packages), no client framework, no external requests, and it works with JavaScript off. Node 22.12+ is only
needed for the site, never for packages.

```bash
python -m aptrepo site-data --storage r2      # export the published state to site/src/data/site-data.json
cd site && npm ci && npm run dev              # live preview; uses src/data/sample.json when there is no export
npm run build                                 # static output in site/dist
cd .. && python -m aptrepo publish-site --storage r2   # export + build + upload (what CI runs)
```

`site-data.json` is the only contract between Python and Astro; see `aptrepo/site.py`. The pages are
uploaded after the packages, and a push that only touches `site/**` republishes them.

## License

[MIT](LICENSE). Packaged software keeps its own licence, shipped in
`/usr/share/doc/<package>/copyright`.
