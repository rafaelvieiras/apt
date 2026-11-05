# Adding a package

Create `packages/<name>.toml`. The file name must equal `name`.

## Upstream already ships a `.deb`

```toml
name = "yazi"
license = "MIT"                 # SPDX; must be on the allowlist in aptrepo/licenses.py
homepage = "https://yazi-rs.github.io"
note = "Static (musl) build. It runs on every Debian and Ubuntu release."   # optional, shown on the Packages page

[source]
type = "github-release"
repo = "sxyazi/yazi"

[build]
kind = "deb"                    # republished untouched
revision = 1

[assets]                        # arch -> release asset name
amd64 = "yazi-x86_64-unknown-linux-musl.deb"
arm64 = "yazi-aarch64-unknown-linux-musl.deb"
```

`homepage`, `license` and `note` are not part of the `.deb`. If you change only one of them, the next
publish run notices, rewrites `index.json` and rebuilds the site. It builds no package and re-signs nothing
that changed, and you do not need `force_index`.

Prefer statically linked (musl) builds: one file then works on every Debian and
Ubuntu release. A glibc build needs `libc6 >=` whatever it was built against and
silently excludes older releases.

## Upstream only ships a tarball

```toml
[build]
kind = "tarball"
revision = 1
license_path = "LICENSE.txt"    # file in the upstream repo at the release tag

[assets]
amd64 = "tool-linux-x86_64.tar.gz"

[package]
section = "utils"
depends = "libc6 (>= 2.34)"
description = """\
One-line synopsis
Longer text.
.
Use a lone dot for a blank line."""
```

The tarball must contain a single top-level directory with `bin/`, `lib/`, `share/`
inside; they are installed under `/usr`. `{version}` and `{deb_version}` work in
`depends`, `replaces` and the other relationship fields.

## Upstream ships a binary or an odd archive layout

Use `kind = "files"`: say which upstream file goes where. `src` is a glob inside the
archive and must match exactly one file, unless `dest` ends with `/` (then it copies every match).
Anything not listed is not shipped. `dest` must be under `/usr/`.

```toml
[build]
kind = "files"
license_path = "LICENSE"

[assets]
amd64 = "tool-*-linux-amd64.tar.gz"     # globs must match exactly one asset

[[file]]
src = "*/bin/tool"
dest = "/usr/bin/tool"                  # executables under /usr/bin are 0755

[[file]]
src = "*/man/*.1"
dest = "/usr/share/man/man1/"
gzip = true                             # man pages are shipped gzipped
```

- A single non-archive asset (a script, a static binary) is addressed by its own name.
- `from = "<asset pattern>"` takes a file from an extra asset listed in `build.extra_assets`.
- A package that is the same on every architecture uses `all = "<asset>"` instead of `amd64`/`arm64`.
- If another repository once shipped the same upstream version with a higher Debian revision
  (for example `0.10.0-1+noble`), set `revision` high enough to sort above it, or `apt upgrade` sees a downgrade.

## Fixing the dependencies of an upstream `.deb`

Add `[package]` with `depends`, `recommends`, `provides`, ... to a `kind = "deb"` recipe. Those fields replace
the ones in the `.deb`; the files are untouched. Use it when the upstream package under-declares a requirement
(for example a missing `libc6 (>= 2.38)`).

### Replacing a distribution package

If Debian/Ubuntu already ship the package, our version must win a plain
`apt upgrade` and not be held back. Check what the distribution package depends
on and publish matching empty packages:

```toml
[[companion]]
name = "neovim-runtime"
description = """\
Transitional package
Empty; keeps upgrades from the distribution packages working."""
```

Companions are published at the same version and depend on `<name> (= version)`.

## Check it

```bash
python -m aptrepo check                       # recipe + licence
python -m aptrepo publish --storage dir:/tmp/bucket --config repo.toml <name>
```

Then install from that bucket in a clean container of the oldest release you
claim to support, **and** do a plain `apt upgrade` from the distribution's own
package. See [setup.md](setup.md#verify).

## Licences

A package whose licence is not on the allowlist is refused. That is deliberate:
only add an SPDX id after confirming it allows redistribution.
