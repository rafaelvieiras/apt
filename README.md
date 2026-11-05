<p align="center">
  <strong>A small, static, signed apt repository with current versions of developer tools. Debian and Ubuntu ship these tools late, or not at all.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
</p>

---

## Use it

The short way: [`setup.sh`](site/public/setup.sh) adds the key and the source, and checks the key
fingerprint. It never installs a package.

```bash
curl -fsSL https://apt.rafaelvieiras.com/setup.sh | sudo sh                    # add the repository
curl -fsSL https://apt.rafaelvieiras.com/setup.sh | sudo sh -s -- --uninstall  # remove it again
sudo apt install neovim yazi                                                   # then use apt as usual
```

To see every step without changing anything, add `--dry-run`. You can also download the file and read it first.
To do it by hand, run the key and source commands below. The last line is yours to run:

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

One suite (`stable`) serves every Debian and Ubuntu release. The packages are static, or they need only an old glibc.
The architectures are `amd64` and `arm64`.
The home page is <https://apt.rafaelvieiras.com> and the full package list is
<https://apt.rafaelvieiras.com/packages>. The same catalogue is in
[`index.json`](https://apt.rafaelvieiras.com/index.json).

| Package | Source | How |
|---|---|---|
| `neovim` | [neovim/neovim](https://github.com/neovim/neovim) | upstream tarball, repackaged as a `.deb` |
| `yazi` | [sxyazi/yazi](https://github.com/sxyazi/yazi) | upstream static (musl) `.deb`, republished without changes |
| `fzf` | [junegunn/fzf](https://github.com/junegunn/fzf) | upstream binary, repackaged as a `.deb` |
| `ripgrep` | [BurntSushi/ripgrep](https://github.com/BurntSushi/ripgrep) | upstream static (musl) build, man page and completions |
| `zoxide` | [ajeetdsouza/zoxide](https://github.com/ajeetdsouza/zoxide) | upstream static (musl) build, man pages and completions |
| `yt-dlp` | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | upstream zipapp. It runs on the system `python3` (>= 3.11). Architecture `all` |
| `ghostty` | [ghostty-org/ghostty](https://ghostty.org) | community `.deb` from [mkasberg/ghostty-ubuntu](https://github.com/mkasberg/ghostty-ubuntu), because Ghostty publishes no Linux binaries. Needs glibc >= 2.38: Ubuntu 24.04+ and Debian 13+ |

Some packages need a newer system than others. If `apt` cannot satisfy a package, it refuses to install
that package and leaves the rest alone. Examples: `yt-dlp` on Ubuntu 22.04, and `ghostty` on Debian 12 and Ubuntu 22.04.

## How it works

```
upstream GitHub release ──► aptrepo (GitHub Actions, every 6 h) ──► Cloudflare R2 ──► apt.rafaelvieiras.com
        (the source)          check, license gate, build,            static files       (Cloudflare CDN)
                              index, sign
```

- **No servers.** The repository is plain files in an R2 bucket. `apt` only needs
  HTTPS `GET`, so there is nothing to run, patch or scale.
- **Almost free at any traffic.** R2 has no egress fees. Packages and `by-hash`
  indexes are immutable (`Cache-Control: immutable`, one year). The few mutable
  files (`InRelease`, `Packages*`, `index.json`) stay in the edge cache for five minutes.
  Most requests never reach R2.
- **Nothing is stored on GitHub.** The binaries live only in R2. GitHub holds the recipes and the code.
- **The state is `index.json`.** A publish reads this one file. It never lists the bucket.
- **It is safe to publish while clients update.** The `.deb` and `by-hash` files go up first,
  and the signed `InRelease` goes up last. No signed index ever points at a missing file.
- **It fails closed.** The run stops on an unknown licence, a missing asset, a checksum mismatch,
  or a signing key that does not match the published public key. A failing package
  does not block the others, but the run still goes red.
- **It never goes backwards.** A retracted or re-tagged upstream release cannot
  downgrade a published package.

## Adding a package

A package is one TOML file in [`packages/`](packages/). The steps are in
[docs/adding-a-package.md](docs/adding-a-package.md).

## Setting it up

The key, the bucket, the domain and the secrets are in [docs/setup.md](docs/setup.md).

## Develop

```bash
python -m aptrepo check                      # validate recipes + licences, offline
python -m unittest discover -s tests -t .    # needs gpg and dpkg-deb
python -m aptrepo plan --storage r2          # what would be published
python -m aptrepo publish --storage dir:/tmp/bucket --config repo.toml   # local dry run
```

You need Python 3.11 or newer. It uses the standard library only. The external tools are `gpg`, `dpkg-deb`
and the `aws` CLI (the `aws` CLI is for R2 uploads only).

### Landing site

The site in [`site/`](site/) is a static [Astro](https://astro.build) project. It has two pages (Home and
Packages), no client framework and no external requests, and it works with JavaScript off. Only the site needs
Node 22.12 or newer. Packages never need it.

```bash
python -m aptrepo site-data --storage r2      # export the published state to site/src/data/site-data.json
cd site && npm ci && npm run dev              # live preview; uses src/data/sample.json when there is no export
npm run build                                 # static output in site/dist
cd .. && python -m aptrepo publish-site --storage r2   # export + build + upload (what CI runs)
```

`site-data.json` is the only contract between Python and Astro. See `aptrepo/site.py`. The workflow uploads the pages
after the packages. A push that touches only `site/**` republishes the pages.

## License

[MIT](LICENSE). Each package keeps its own licence. It is in
`/usr/share/doc/<package>/copyright`.
