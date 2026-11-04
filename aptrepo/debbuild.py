"""Turn upstream artifacts into ``.deb`` files."""

from __future__ import annotations

import glob
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .recipe import Recipe

MAINTAINER = "Rafael Vieiras <hello@rafaelvieiras.com>"
VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9.+~]*$")


class BuildError(RuntimeError):
    pass


def _run(cmd: list[str], env: dict | None = None) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise BuildError(f"{' '.join(cmd)}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def control_field(deb: Path, field: str) -> str:
    return _run(["dpkg-deb", "-f", str(deb), field]).strip()


def control_text(deb: Path) -> str:
    """Raw control stanza of ``deb`` (no trailing newline)."""
    return _run(["dpkg-deb", "-f", str(deb)]).rstrip("\n")


def upstream_version(tag: str) -> str:
    version = tag[1:] if tag[:1] in "vV" else tag
    if not VERSION_RE.match(version):
        version = version.replace("-", ".")  # e.g. "1.3.1-0-ppa2"
    if not VERSION_RE.match(version):
        raise BuildError(f"cannot derive a Debian version from upstream tag {tag!r}")
    return version


def pool_path(name: str, version: str, arch: str) -> str:
    prefix = name[:4] if name.startswith("lib") else name[:1]
    return f"pool/main/{prefix}/{name}/{name}_{version.split(':')[-1]}_{arch}.deb"


def hashes(path: Path) -> dict[str, str | int]:
    md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
            size += len(chunk)
    return {
        "size": size,
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def _subst(value: str, version: str, deb_version: str) -> str:
    return value.replace("{version}", version).replace("{deb_version}", deb_version)


def _format_description(text: str) -> str:
    lines = text.strip("\n").splitlines()
    out = [lines[0].strip()]
    for line in lines[1:]:
        out.append(" " + (line.rstrip() or "."))
    return "\n".join(out)


def _extract(tarball: Path, dest: Path) -> None:
    """Extract a tarball dropping its single top-level directory."""
    with tarfile.open(tarball) as tar:
        members = []
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= 1:
                continue
            member.name = str(Path(*parts[1:]))
            if member.name.startswith("..") or os.path.isabs(member.name):
                raise BuildError(f"unsafe path in tarball: {member.name}")
            members.append(member)
        tar.extractall(dest, members=members, filter="data")


def build_from_tarball(
    recipe: Recipe,
    arch: str,
    version: str,
    tarball: Path,
    license_text: str,
    out_dir: Path,
    epoch: int,
) -> Path:
    """Wrap an upstream tarball (``bin/ lib/ share/``) into a ``.deb`` under /usr."""
    with tempfile.TemporaryDirectory(prefix="aptrepo-") as tmp:
        root = Path(tmp) / "root"
        usr = root / "usr"
        usr.mkdir(parents=True)
        _extract(tarball, usr)
        return _finish(recipe, arch, version, root, license_text, out_dir, epoch)


def _install_file(src: Path, dest: Path, mode: int, compress: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if compress:
        dest = dest.with_name(dest.name + ".gz")
        with src.open("rb") as fh, dest.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
                shutil.copyfileobj(fh, gz)
    else:
        shutil.copyfile(src, dest)
    dest.chmod(mode)


def build_from_files(
    recipe: Recipe,
    arch: str,
    version: str,
    assets: dict[str, tuple[str, Path]],
    license_text: str,
    out_dir: Path,
    epoch: int,
) -> Path:
    """Place chosen upstream files at fixed paths.

    ``assets`` maps the recipe's asset pattern -> (real asset name, downloaded file).
    Tar archives are unpacked and addressed by glob (``*/rg``); any other asset is a
    single file addressed by its own name.
    """
    with tempfile.TemporaryDirectory(prefix="aptrepo-") as tmp:
        tmp_path = Path(tmp)
        trees: dict[str, Path] = {}
        for key, (name, path) in assets.items():
            tree = tmp_path / "src" / key.replace("/", "_")
            tree.mkdir(parents=True)
            if tarfile.is_tarfile(path):
                with tarfile.open(path) as tar:
                    for member in tar.getmembers():
                        if member.name.startswith("..") or os.path.isabs(member.name):
                            raise BuildError(f"unsafe path in {name}: {member.name}")
                    tar.extractall(tree, filter="data")
            else:
                shutil.copyfile(path, tree / name)
            trees[key] = tree

        main = next(iter(assets))  # the per-arch asset is always first
        root = tmp_path / "root"
        root.mkdir()
        for spec in recipe.files:
            tree = trees.get(spec.get("from", main))
            if tree is None:
                raise BuildError(f"{recipe.name}: [[file]] from={spec.get('from')!r} is not a downloaded asset")
            matches = sorted(glob.glob(str(tree / _subst(spec["src"], version, version))))
            matches = [m for m in matches if Path(m).is_file()]
            into_dir = spec["dest"].endswith("/")  # many files, keep their names
            if (into_dir and not matches) or (not into_dir and len(matches) != 1):
                raise BuildError(
                    f"{recipe.name}: {spec['src']!r} matched {len(matches)} files, "
                    f"expected {'at least 1' if into_dir else 'exactly 1'}"
                )
            executable = spec["dest"].startswith(("/usr/bin/", "/usr/sbin/", "/usr/lib/"))
            mode = int(str(spec.get("mode", "0755" if executable else "0644")), 8)
            for match in matches:
                dest = root / spec["dest"].lstrip("/")
                if into_dir:
                    dest = dest / Path(match).name
                _install_file(Path(match), dest, mode, bool(spec.get("gzip", False)))
        return _finish(recipe, arch, version, root, license_text, out_dir, epoch)


def _finish(recipe: Recipe, arch: str, version: str, root: Path, license_text: str,
            out_dir: Path, epoch: int) -> Path:
    """Add copyright, md5sums and control to ``root`` and build the ``.deb``."""
    pkg = recipe.package
    deb_version = f"{version}-{recipe.revision}"
    doc = root / "usr" / "share" / "doc" / recipe.name
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "copyright").write_text(
        f"Packaged from {recipe.homepage}\nLicense: {recipe.license}\n\n{license_text}\n"
    )

    md5s: list[str] = []
    size_kib = 0
    for path in sorted(root.rglob("*")):
        os.utime(path, (epoch, epoch), follow_symlinks=False)
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            size_kib += (path.stat().st_size + 1023) // 1024
            md5s.append(f"{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(root)}")
    os.utime(root, (epoch, epoch))

    debian = root / "DEBIAN"
    debian.mkdir()
    (debian / "md5sums").write_text("\n".join(md5s) + "\n")
    fields = [
        ("Package", recipe.name),
        ("Version", deb_version),
        ("Architecture", arch),
        ("Maintainer", MAINTAINER),
        ("Installed-Size", str(size_kib)),
    ]
    for key in ("Depends", "Recommends", "Suggests", "Provides", "Conflicts", "Replaces", "Breaks"):
        value = pkg.get(key.lower())
        if value:
            fields.append((key, _subst(value, version, deb_version)))
    fields += [
        ("Section", pkg["section"]),
        ("Priority", pkg.get("priority", "optional")),
        ("Homepage", recipe.homepage),
        ("Description", _format_description(pkg["description"])),
    ]
    (debian / "control").write_text("".join(f"{k}: {v}\n" for k, v in fields))
    debian.chmod(0o755)

    out_dir.mkdir(parents=True, exist_ok=True)
    deb = out_dir / f"{recipe.name}_{deb_version}_{arch}.deb"
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
    _run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(root), str(deb)], env=env)
    return deb


_OVERRIDABLE = ("depends", "recommends", "suggests", "provides", "conflicts", "replaces", "breaks")


def _rewrite_control(src: Path, dest: Path, overrides: dict[str, str], epoch: int) -> None:
    """Rebuild ``src`` with some relationship fields replaced. Files are untouched."""
    with tempfile.TemporaryDirectory(prefix="aptrepo-") as tmp:
        root = Path(tmp) / "root"
        _run(["dpkg-deb", "--raw-extract", str(src), str(root)])
        control = root / "DEBIAN" / "control"
        out: list[str] = []
        skipping = False
        for line in control.read_text().splitlines():
            if line[:1] in " \t":
                if not skipping:
                    out.append(line)
                continue
            field = line.split(":", 1)[0]
            skipping = field in overrides
            if not skipping:
                out.append(line)
        # keep the descriptive fields last, like dpkg does
        desc = next((i for i, l in enumerate(out) if l.startswith("Description:")), len(out))
        out[desc:desc] = [f"{k}: {v}" for k, v in overrides.items()]
        control.write_text("\n".join(out) + "\n")
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
        _run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(root), str(dest)], env=env)


def adopt_deb(recipe: Recipe, arch: str, deb: Path, destination: Path, epoch: int = 0) -> tuple[Path, str]:
    """Validate an upstream ``.deb`` and copy it into the pool. Returns (path, version)."""
    if control_field(deb, "Package") != recipe.name:
        raise BuildError(f"{deb.name}: Package is not {recipe.name!r}")
    if control_field(deb, "Architecture") != arch:
        raise BuildError(f"{deb.name}: Architecture is not {arch!r}")
    version = control_field(deb, "Version")
    final = destination / Path(pool_path(recipe.name, version, arch)).name
    destination.mkdir(parents=True, exist_ok=True)
    overrides = {k.capitalize(): v for k, v in recipe.package.items() if k in _OVERRIDABLE}
    if overrides:
        _rewrite_control(deb, final, overrides, epoch)
    else:
        shutil.copyfile(deb, final)
    return final, version


def build_companion(recipe: Recipe, spec: dict, arch: str, deb_version: str, out_dir: Path, epoch: int) -> Path:
    """Empty package that only depends on the main one, so old names keep upgrading."""
    name = spec["name"]
    with tempfile.TemporaryDirectory(prefix="aptrepo-") as tmp:
        root = Path(tmp) / "root"
        debian = root / "DEBIAN"
        debian.mkdir(parents=True)
        debian.chmod(0o755)
        fields = [
            ("Package", name),
            ("Version", deb_version),
            ("Architecture", arch),
            ("Maintainer", MAINTAINER),
            ("Depends", f"{recipe.name} (= {deb_version})"),
            ("Section", spec.get("section", "oldlibs")),
            ("Priority", "optional"),
            ("Homepage", recipe.homepage),
            ("Description", _format_description(spec["description"])),
        ]
        (debian / "control").write_text("".join(f"{k}: {v}\n" for k, v in fields))
        out_dir.mkdir(parents=True, exist_ok=True)
        deb = out_dir / f"{name}_{deb_version}_{arch}.deb"
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
        _run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(root), str(deb)], env=env)
    return deb
