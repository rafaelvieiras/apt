"""Repository state and static index rendering (Packages, Release, by-hash).

``index.json`` is both the public machine-readable catalogue and the only state
the publisher needs: every ``Packages`` stanza is rebuilt from it, so a publish
never has to list or download the pool.
"""

from __future__ import annotations

import gzip
import hashlib
import lzma
import time
from dataclasses import dataclass, field
from email.utils import formatdate

from . import debversion

SCHEMA = 1


@dataclass
class RepoConfig:
    origin: str
    label: str
    suite: str
    component: str
    architectures: list[str]
    base_url: str
    description: str
    key_file: str
    key_name: str
    retain: int = 3

    @classmethod
    def from_toml(cls, data: dict) -> "RepoConfig":
        repo = data["repository"]
        return cls(
            origin=repo["origin"],
            label=repo.get("label", repo["origin"]),
            suite=repo.get("suite", "stable"),
            component=repo.get("component", "main"),
            architectures=list(repo["architectures"]),
            base_url=repo["base_url"].rstrip("/"),
            description=repo.get("description", ""),
            key_file=repo["key_file"],
            key_name=repo.get("key_name", "rafaelvieiras-apt"),
            retain=int(repo.get("retain", 3)),
        )


def empty_state() -> dict:
    return {"schema": SCHEMA, "generated": "", "packages": {}, "byhash": {"current": [], "previous": []}}


def load_state(raw: bytes | None) -> dict:
    if not raw:
        return empty_state()
    import json

    state = json.loads(raw)
    if state.get("schema") != SCHEMA:
        raise ValueError(f"unsupported index.json schema {state.get('schema')!r}")
    state.setdefault("byhash", {"current": [], "previous": []})
    return state


def newest_version(entry: dict) -> str | None:
    versions = list(entry.get("versions", {}))
    if not versions:
        return None
    return max(versions, key=debversion.sort_key)


def newest_upstream(entry: dict) -> str | None:
    best = None
    for info in entry.get("versions", {}).values():
        up = info.get("upstream_version")
        if up and (best is None or debversion.compare(up, best) > 0):
            best = up
    return best


def has_source(entry: dict, source: str) -> bool:
    return any(v.get("source") == source for v in entry.get("versions", {}).values())


def add_version(
    state: dict,
    *,
    name: str,
    homepage: str,
    license: str,
    version: str,
    upstream_version: str,
    source: str,
    released: str,
    arches: dict[str, dict],
) -> None:
    entry = state["packages"].setdefault(name, {"versions": {}})
    entry["homepage"] = homepage
    entry["license"] = license
    entry["versions"][version] = {
        "upstream_version": upstream_version,
        "source": source,
        "released": released,
        "arch": arches,
    }
    first = next(iter(arches.values()))["control"]
    entry["description"] = _short_description(first)


def _short_description(control: str) -> str:
    for line in control.splitlines():
        if line.startswith("Description:"):
            return line.split(":", 1)[1].strip()
    return ""


def prune(state: dict, retain: int) -> list[str]:
    """Drop all but the ``retain`` newest versions. Returns pool keys to delete."""
    doomed: list[str] = []
    for entry in state["packages"].values():
        ordered = sorted(entry["versions"], key=debversion.sort_key, reverse=True)
        for version in ordered[retain:]:
            for info in entry["versions"][version]["arch"].values():
                doomed.append(info["filename"])
            del entry["versions"][version]
    return doomed


def render_packages(state: dict, arch: str) -> bytes:
    stanzas: list[str] = []
    for name in sorted(state["packages"]):
        entry = state["packages"][name]
        for version in sorted(entry["versions"], key=debversion.sort_key, reverse=True):
            arches = entry["versions"][version]["arch"]
            info = arches.get(arch) or arches.get("all")  # arch-independent: listed everywhere
            if not info:
                continue
            stanzas.append(
                f"{info['control']}\n"
                f"Filename: {info['filename']}\n"
                f"Size: {info['size']}\n"
                f"MD5sum: {info['md5']}\n"
                f"SHA1: {info['sha1']}\n"
                f"SHA256: {info['sha256']}"
            )
    return ("\n\n".join(stanzas) + "\n").encode() if stanzas else b""


def compress(data: bytes) -> dict[str, bytes]:
    return {
        "Packages": data,
        "Packages.gz": gzip.compress(data, compresslevel=9, mtime=0),
        "Packages.xz": lzma.compress(data, format=lzma.FORMAT_XZ, preset=6),
    }


@dataclass
class Rendered:
    """Everything under ``dists/<suite>/`` except the signature files."""

    files: dict[str, bytes] = field(default_factory=dict)  # key -> content
    byhash: dict[str, bytes] = field(default_factory=dict)  # key -> content
    release: bytes = b""


def _digest(data: bytes, algo: str) -> str:
    return hashlib.new(algo, data).hexdigest()


def render_dists(state: dict, cfg: RepoConfig, now: float | None = None) -> Rendered:
    base = f"dists/{cfg.suite}"
    out = Rendered()
    listing: list[tuple[str, bytes]] = []  # path relative to base, content

    for arch in cfg.architectures:
        folder = f"{cfg.component}/binary-{arch}"
        payloads = compress(render_packages(state, arch))
        payloads["Release"] = (
            f"Archive: {cfg.suite}\nComponent: {cfg.component}\n"
            f"Origin: {cfg.origin}\nLabel: {cfg.label}\nArchitecture: {arch}\n"
        ).encode()
        for fname, data in payloads.items():
            rel = f"{folder}/{fname}"
            out.files[f"{base}/{rel}"] = data
            listing.append((rel, data))
            if fname != "Release":
                sha = _digest(data, "sha256")
                out.byhash[f"{base}/{folder}/by-hash/SHA256/{sha}"] = data

    def block(algo: str, label: str) -> str:
        width = max(len(str(len(d))) for _, d in listing)
        lines = [f"{label}:"]
        for rel, data in sorted(listing):
            lines.append(f" {_digest(data, algo)} {len(data):>{width}} {rel}")
        return "\n".join(lines)

    date = formatdate(now if now is not None else time.time(), usegmt=True)
    header = [
        f"Origin: {cfg.origin}",
        f"Label: {cfg.label}",
        f"Suite: {cfg.suite}",
        f"Codename: {cfg.suite}",
        f"Date: {date}",
        f"Architectures: {' '.join(cfg.architectures)}",
        f"Components: {cfg.component}",
        f"Description: {cfg.description}" if cfg.description else None,
        "Acquire-By-Hash: yes",
    ]
    text = "\n".join(h for h in header if h) + "\n"
    text += "\n".join([block("md5", "MD5Sum"), block("sha1", "SHA1"), block("sha256", "SHA256")])
    out.release = (text + "\n").encode()
    out.files[f"{base}/Release"] = out.release
    return out
