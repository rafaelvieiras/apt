"""Debian version comparison (Debian Policy section 5.6.12), no subprocess needed."""

from __future__ import annotations

from functools import cmp_to_key


def _order(ch: str) -> int:
    if ch == "~":
        return -1
    if ch.isalpha():
        return ord(ch)
    return ord(ch) + 256


def _cmp_part(a: str, b: str) -> int:
    i = j = 0
    while i < len(a) or j < len(b):
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _order(a[i]) if i < len(a) and not a[i].isdigit() else 0
            bc = _order(b[j]) if j < len(b) and not b[j].isdigit() else 0
            if ac != bc:
                return -1 if ac < bc else 1
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        diff = 0
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not diff:
                diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if diff:
            return -1 if diff < 0 else 1
    return 0


def _split(version: str) -> tuple[int, str, str]:
    epoch = 0
    if ":" in version:
        head, version = version.split(":", 1)
        epoch = int(head)
    revision = ""
    if "-" in version:
        version, revision = version.rsplit("-", 1)
    return epoch, version, revision


def compare(a: str, b: str) -> int:
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    return _cmp_part(ua, ub) or _cmp_part(ra, rb)


sort_key = cmp_to_key(compare)
