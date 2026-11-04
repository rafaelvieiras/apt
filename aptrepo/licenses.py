"""Licence gate: only redistribute packages whose licence allows it.

Fails closed: an identifier that is not on the allowlist stops the build.
Recipes declare an SPDX expression such as ``Apache-2.0 AND Vim``.
"""

from __future__ import annotations

import re

ALLOWED = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "Artistic-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC0-1.0",
        "EUPL-1.2",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "ISC",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MIT",
        "MPL-2.0",
        "Unlicense",
        "Vim",
        "Zlib",
    }
)

_OPERATORS = {"AND", "OR", "WITH"}


class LicenseError(ValueError):
    pass


def identifiers(expression: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9.+\-]+", expression)
    return [t for t in tokens if t.upper() not in _OPERATORS]


def check(expression: str) -> None:
    ids = identifiers(expression)
    if not ids:
        raise LicenseError(f"empty licence expression: {expression!r}")
    bad = [i for i in ids if i not in ALLOWED]
    if bad:
        raise LicenseError(
            f"licence {', '.join(bad)} is not on the redistribution allowlist "
            f"(aptrepo/licenses.py); refusing to package"
        )
