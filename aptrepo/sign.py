"""Signing with GnuPG. The private key never touches argv or the repository."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


class SignError(RuntimeError):
    pass


def _gpg(home: Path, args: list[str], data: bytes | None = None, passphrase: str | None = None) -> bytes:
    cmd = ["gpg", "--homedir", str(home), "--batch", "--no-tty", "--yes"]
    pass_file = None
    try:
        if passphrase:
            pass_file = tempfile.NamedTemporaryFile("w", delete=False, dir=home)
            os.chmod(pass_file.name, 0o600)
            pass_file.write(passphrase)
            pass_file.close()
            cmd += ["--pinentry-mode", "loopback", "--passphrase-file", pass_file.name]
        proc = subprocess.run(cmd + args, input=data, capture_output=True)
    finally:
        if pass_file:
            os.unlink(pass_file.name)
    if proc.returncode != 0:
        raise SignError(f"gpg {' '.join(args[:2])} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


class Signer:
    """Imports a private key into a throw-away keyring and signs with it."""

    def __init__(self, private_key: str, passphrase: str | None = None):
        self._tmp = tempfile.TemporaryDirectory(prefix="aptrepo-gnupg-")
        self.home = Path(self._tmp.name)
        self.home.chmod(0o700)
        self.passphrase = passphrase or None
        _gpg(self.home, ["--import"], private_key.encode(), self.passphrase)
        listing = _gpg(self.home, ["--list-secret-keys", "--with-colons"]).decode()
        self.fingerprint = next(
            (line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")), ""
        )
        if not self.fingerprint:
            raise SignError("no secret key found after import")

    def clearsign(self, data: bytes) -> bytes:
        return _gpg(
            self.home,
            ["--local-user", self.fingerprint, "--digest-algo", "SHA512", "--clearsign"],
            data,
            self.passphrase,
        )

    def detach_sign(self, data: bytes) -> bytes:
        return _gpg(
            self.home,
            ["--local-user", self.fingerprint, "--digest-algo", "SHA512", "--armor", "--detach-sign"],
            data,
            self.passphrase,
        )

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "Signer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def public_fingerprint(armored: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="aptrepo-gnupg-") as tmp:
        home = Path(tmp)
        home.chmod(0o700)
        out = _gpg(home, ["--show-keys", "--with-colons"], armored).decode()
    for line in out.splitlines():
        if line.startswith("fpr:"):
            return line.split(":")[9]
    raise SignError("no public key found")


def dearmor(armored: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="aptrepo-gnupg-") as tmp:
        home = Path(tmp)
        home.chmod(0o700)
        return _gpg(home, ["--dearmor"], armored)


def verify_clearsigned(public_armored: bytes, signed: bytes) -> None:
    """Raise unless ``signed`` verifies against ``public_armored``."""
    with tempfile.TemporaryDirectory(prefix="aptrepo-gnupg-") as tmp:
        home = Path(tmp)
        home.chmod(0o700)
        _gpg(home, ["--import"], public_armored)
        _gpg(home, ["--verify"], signed)
