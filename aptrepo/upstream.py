"""Resolve and download upstream GitHub releases."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = os.environ.get("APTREPO_GITHUB_API", "https://api.github.com").rstrip("/")
UA = "rafaelvieiras-apt/0.1 (+https://github.com/rafaelvieiras/apt)"


class UpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str | None  # from GitHub's asset digest, when present


@dataclass(frozen=True)
class Release:
    tag: str
    published: str
    assets: dict[str, Asset]

    @property
    def version(self) -> str:
        return self.tag[1:] if self.tag[:1] in "vV" else self.tag


def _open(url: str, accept: str | None = None):
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"
    last: Exception | None = None
    for attempt in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise UpstreamError(f"GET {url}: HTTP {exc.code}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        time.sleep(2**attempt)
    raise UpstreamError(f"GET {url}: {last}")


def latest_release(repo: str) -> Release:
    """Newest stable release (GitHub excludes drafts and prereleases)."""
    with _open(f"{API}/repos/{repo}/releases/latest", "application/vnd.github+json") as resp:
        data = json.load(resp)
    assets: dict[str, Asset] = {}
    for item in data.get("assets", []):
        digest = item.get("digest") or ""
        assets[item["name"]] = Asset(
            name=item["name"],
            url=item["browser_download_url"],
            size=int(item.get("size", 0)),
            sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
        )
    return Release(tag=data["tag_name"], published=data.get("published_at", ""), assets=assets)


def find_asset(release: Release, pattern: str) -> Asset:
    """The one asset whose name matches ``pattern`` (a name or an fnmatch glob)."""
    if pattern in release.assets:
        return release.assets[pattern]
    hits = [a for n, a in release.assets.items() if fnmatch.fnmatchcase(n, pattern)]
    if len(hits) != 1:
        names = ", ".join(sorted(a.name for a in hits)) or "none"
        raise UpstreamError(f"release {release.tag}: {pattern!r} matched {len(hits)} assets ({names})")
    return hits[0]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(asset: Asset, dest: Path) -> str:
    """Download ``asset`` to ``dest`` and verify it. Returns the SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _open(asset.url) as resp, dest.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    got = sha256_file(dest)
    if asset.sha256 and got != asset.sha256:
        dest.unlink(missing_ok=True)
        raise UpstreamError(f"{asset.name}: sha256 mismatch (expected {asset.sha256}, got {got})")
    return got


def fetch_text(url: str) -> str:
    with _open(url) as resp:
        return resp.read().decode("utf-8", "replace")
