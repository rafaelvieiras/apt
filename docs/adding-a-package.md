# Adding a package

Create `packages/<name>.toml`. The file name must equal `name`.

## Upstream already ships a `.deb`

```toml
name = "yazi"
license = "MIT"                 # SPDX; must be on the allowlist in aptrepo/licenses.py
homepage = "https://yazi-rs.github.io"

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
