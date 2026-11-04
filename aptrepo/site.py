"""Landing site: data export for the Astro project in ``site/`` and the uploader for its output.

The pages themselves live in ``site/`` (Astro, static output). This module is the
only bridge between the two worlds:

* :func:`export` turns the repository state (``index.json``) into the small
  ``site-data.json`` the pages read at build time.
* :func:`upload` publishes the built ``site/dist/`` through the normal storage
  layer, with the Cloudflare constraints of this bucket in mind (see below).

Cloudflare serves the bucket with exactly one rewrite rule, ``/`` -> ``/index.html``,
and R2 does not serve index documents. So every page other than the home page is
stored twice: as ``packages.html`` and as the extensionless key ``packages``,
which is what the site links to (``/packages``).
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import repo, sign
from .storage import HTML, Storage

SCHEMA = 1
DATA_PATH = "site/src/data/site-data.json"

# A site upload must never be able to shadow apt's own paths or the public key.
RESERVED_PREFIXES = ("dists/", "pool/", "key.")
RESERVED_KEYS = frozenset({"index.json", "dists", "pool"})


class SiteError(RuntimeError):
    pass


def _safe_url(url: str) -> str:
    """Only http(s) links survive; the pages put this straight into ``href``."""
    return url if re.match(r"https?://", url or "") else ""


def is_transitional(entry: dict) -> bool:
    """Debian convention: empty compatibility packages say so in their synopsis."""
    return entry.get("description", "").lower().startswith("transitional")


def pretty_fingerprint(fingerprint: str) -> str:
    """``D7A3 DA0B EA6E 67AF ADA5  C504 675F 04D1 1720 08F5`` (groups of four, two blocks of five)."""
    groups = [fingerprint[i : i + 4] for i in range(0, len(fingerprint), 4)]
    return "  ".join(" ".join(groups[i : i + 5]) for i in range(0, len(groups), 5))


def _utc(now: float | None) -> str:
    stamp = datetime.fromtimestamp(now, timezone.utc) if now is not None else datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def export(state: dict, cfg: repo.RepoConfig, fingerprint: str, *, now: float | None = None) -> dict:
    """Everything the pages need, and nothing else. Pure: no I/O."""
    packages = []
    for name in sorted(state["packages"]):
        entry = state["packages"][name]
        newest = repo.newest_version(entry)
        if newest is None:
            continue
        info = entry["versions"][newest]
        packages.append(
            {
                "name": name,
                "version": info.get("upstream_version") or newest,
                "debVersion": newest,
                "released": info.get("released", ""),
                "arches": sorted(info["arch"]),
                "license": entry.get("license", ""),
                "homepage": _safe_url(entry.get("homepage", "")),
                "description": entry.get("description", ""),
                "note": entry.get("note", ""),
                "transitional": is_transitional(entry),
            }
        )
    return {
        "schema": SCHEMA,
        "generated": _utc(now),
        "indexGenerated": state.get("generated", ""),
        "repo": {
            "name": cfg.origin,
            "description": cfg.description,
            "baseUrl": cfg.base_url,
            "suite": cfg.suite,
            "component": cfg.component,
            "architectures": list(cfg.architectures),
            "retain": cfg.retain,
        },
        "fingerprint": {"raw": fingerprint, "pretty": pretty_fingerprint(fingerprint)},
        "packages": packages,
    }


def write_data(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def export_from_storage(
    storage: Storage, cfg: repo.RepoConfig, key_path: Path, out: Path, *, index: Path | None = None, now: float | None = None
) -> dict:
    """Read the published state (or a local ``index.json``) and write ``site-data.json``."""
    raw = index.read_bytes() if index else storage.get("index.json")
    if not raw:
        raise SiteError("no index.json to build the site from; publish packages first")
    fingerprint = sign.public_fingerprint(key_path.read_bytes())
    data = export(repo.load_state(raw), cfg, fingerprint, now=now)
    write_data(out, data)
    return data


# --- upload ---------------------------------------------------------------------------------


def is_reserved(key: str) -> bool:
    lower = key.lower()
    return lower in RESERVED_KEYS or lower.startswith(RESERVED_PREFIXES)


def plan_upload(dist: Path) -> list[tuple[str, Path, str | None]]:
    """``(key, file, content type override)`` for every object, in upload order.

    Raises :class:`SiteError` before anything is uploaded if any key (including the
    extensionless copies) could shadow an apt path.
    """
    dist = Path(dist)
    if not (dist / "index.html").is_file():
        raise SiteError(f"{dist}/index.html not found; run the site build first")
    assets: list[tuple[str, Path, str | None]] = []
    files: list[tuple[str, Path, str | None]] = []
    pages: list[tuple[str, Path, str | None]] = []
    for path in sorted(dist.rglob("*")):
        if path.is_symlink():
            raise SiteError(f"refusing symlink in site output: {path}")
        if not path.is_file():
            continue
        key = path.relative_to(dist).as_posix()
        if key.endswith(".part") or key.startswith(".") or "/." in key:
            continue  # editor and tooling droppings never belong in the bucket
        copies = [(key, None)]
        if key.endswith(".html") and key != "index.html":
            copies.append((key[: -len(".html")], HTML))  # /packages -> object "packages"
        for target, ctype in copies:
            if is_reserved(target):
                raise SiteError(f"refusing to upload {target!r}: it would shadow a repository path")
            entry = (target, path, ctype)
            (assets if target.startswith("_astro/") else pages if key.endswith(".html") else files).append(entry)
    # Assets, then other files, then pages; the home page last, so no page ever
    # points at an object that is not there yet.
    pages.sort(key=lambda item: item[0] == "index.html")
    return assets + files + pages


def upload(storage: Storage, dist: Path, log=print) -> list[str]:
    """Publish ``dist`` and return the keys written."""
    keys = []
    for key, path, ctype in plan_upload(dist):
        storage.put_file(key, path, ctype)
        keys.append(key)
    log(f"uploaded {len(keys)} site objects")
    return keys


def build(site_dir: Path, log=print) -> Path:
    """``npm ci && npm run build``. The only place Node is needed."""
    site_dir = Path(site_dir)
    for cmd in (["npm", "ci"], ["npm", "run", "build"]):
        log("$ " + " ".join(cmd))
        try:
            proc = subprocess.run(cmd, cwd=site_dir)
        except FileNotFoundError:
            raise SiteError("npm is required to build the site (Node 22.12+)") from None
        if proc.returncode != 0:
            raise SiteError(f"{' '.join(cmd)} failed")
    return site_dir / "dist"
