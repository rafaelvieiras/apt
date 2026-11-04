"""Object storage backends: a local directory (tests, dry runs) and Cloudflare R2.

R2 is reached through its S3 API with the ``aws`` CLI. Credentials come from the
environment (``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``) and are never put
on a command line.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"


def cache_control(key: str) -> str:
    """Cache policy by key.

    Content-addressed or versioned files never change, so they cache for a year.
    The few mutable entry points (Release, InRelease, index.json, ...) cache for
    five minutes, which is enough to absorb traffic and still lets updates land.
    """
    if key.startswith(("pool/", "_astro/")) or "/by-hash/" in key:
        return IMMUTABLE  # _astro/ holds the landing page's content-hashed assets
    return SHORT


HTML = "text/html; charset=utf-8"

# Explicit, so the answer does not depend on the machine's mime database.
_TYPES = {
    ".asc": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".deb": "application/vnd.debian.binary-package",
    ".gz": "application/octet-stream",
    ".xz": "application/octet-stream",
    ".json": "application/json",
    ".html": HTML,
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".xml": "application/xml; charset=utf-8",
    ".webmanifest": "application/manifest+json",
}


def content_type(key: str) -> str:
    name = key.rsplit("/", 1)[-1]
    if name in ("Release", "InRelease", "Packages", "Release.gpg"):
        return "text/plain; charset=utf-8"
    dot = name.rfind(".")
    if dot > 0 and name[dot:].lower() in _TYPES:
        return _TYPES[name[dot:].lower()]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class Storage(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes, ctype: str | None = None) -> None: ...
    def put_file(self, key: str, path: Path, ctype: str | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class DirStorage:
    """Plain directory. ``headers`` and ``types`` record what a real bucket would be told."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.headers: dict[str, str] = {}
        self.types: dict[str, str] = {}

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes storage root: {key}")
        return path

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def put(self, key: str, data: bytes, ctype: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        self.headers[key] = cache_control(key)
        self.types[key] = ctype or content_type(key)

    def put_file(self, key: str, path: Path, ctype: str | None = None) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        self.headers[key] = cache_control(key)
        self.types[key] = ctype or content_type(key)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class R2Storage:
    def __init__(self, bucket: str, endpoint: str):
        self.bucket = bucket
        self.endpoint = endpoint
        if shutil.which("aws") is None:
            raise RuntimeError("the 'aws' CLI is required for R2 storage")
        for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            if not os.environ.get(var):
                raise RuntimeError(f"{var} is not set")

    def _aws(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        env = dict(
            os.environ,
            AWS_DEFAULT_REGION="auto",
            AWS_EC2_METADATA_DISABLED="true",
            # Recent CLIs add CRC checksums that R2 does not always accept.
            AWS_REQUEST_CHECKSUM_CALCULATION="when_required",
            AWS_RESPONSE_CHECKSUM_VALIDATION="when_required",
            AWS_MAX_ATTEMPTS="3",
            AWS_RETRY_MODE="standard",
        )
        cmd = ["aws", "--endpoint-url", self.endpoint, "--cli-connect-timeout", "15",
               "--cli-read-timeout", "120", *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, env=env, stdin=subprocess.DEVNULL, timeout=600)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"aws {args[0]} {args[1]} timed out") from None
        if check and proc.returncode != 0:
            raise RuntimeError(f"aws {args[0]} {args[1]} failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc

    def get(self, key: str) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "obj"
            proc = self._aws(["s3api", "get-object", "--bucket", self.bucket, "--key", key, str(dest)], check=False)
            if proc.returncode != 0:
                if b"NoSuchKey" in proc.stderr or b"Not Found" in proc.stderr:
                    return None
                raise RuntimeError(f"get {key}: {proc.stderr.decode(errors='replace').strip()}")
            return dest.read_bytes()

    def put_file(self, key: str, path: Path, ctype: str | None = None) -> None:
        self._aws(
            [
                "s3api", "put-object", "--bucket", self.bucket, "--key", key, "--body", str(path),
                "--cache-control", cache_control(key), "--content-type", ctype or content_type(key),
            ]
        )

    def put(self, key: str, data: bytes, ctype: str | None = None) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obj"
            path.write_bytes(data)
            self.put_file(key, path, ctype)

    def delete(self, key: str) -> None:
        self._aws(["s3api", "delete-object", "--bucket", self.bucket, "--key", key])

    def exists(self, key: str) -> bool:
        proc = self._aws(["s3api", "head-object", "--bucket", self.bucket, "--key", key], check=False)
        return proc.returncode == 0


def open_storage(spec: str) -> Storage:
    """``dir:PATH`` or ``r2`` (reads R2_BUCKET and R2_ENDPOINT from the environment)."""
    if spec.startswith("dir:"):
        return DirStorage(Path(spec[4:]))
    if spec == "r2":
        bucket, endpoint = os.environ.get("R2_BUCKET"), os.environ.get("R2_ENDPOINT")
        if not bucket or not endpoint:
            raise RuntimeError("R2_BUCKET and R2_ENDPOINT must be set for --storage r2")
        return R2Storage(bucket, endpoint)
    raise ValueError(f"unknown storage {spec!r}; use 'dir:PATH' or 'r2'")
