"""Turn upstream artifacts into ``.deb`` files."""

from __future__ import annotations

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
    pkg = recipe.package
    deb_version = f"{version}-{recipe.revision}"
    with tempfile.TemporaryDirectory(prefix="aptrepo-") as tmp:
        root = Path(tmp) / "root"
        usr = root / "usr"
        usr.mkdir(parents=True)
        _extract(tarball, usr)
        doc = usr / "share" / "doc" / recipe.name
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
                md5s.append(
                    f"{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(root)}"
                )
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
        for key in ("Depends", "Recommends", "Provides", "Conflicts", "Replaces", "Breaks"):
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


def adopt_deb(recipe: Recipe, arch: str, deb: Path, destination: Path) -> tuple[Path, str]:
    """Validate an upstream ``.deb`` and copy it into the pool. Returns (path, version)."""
    if control_field(deb, "Package") != recipe.name:
        raise BuildError(f"{deb.name}: Package is not {recipe.name!r}")
    if control_field(deb, "Architecture") != arch:
        raise BuildError(f"{deb.name}: Architecture is not {arch!r}")
    version = control_field(deb, "Version")
    final = destination / Path(pool_path(recipe.name, version, arch)).name
    destination.mkdir(parents=True, exist_ok=True)
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
