"""Package recipes: one TOML file per upstream project in ``packages/``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("deb", "tarball", "files")
ARCHES = ("amd64", "arm64", "all")  # "all" = architecture-independent


class RecipeError(ValueError):
    pass


@dataclass(frozen=True)
class Recipe:
    name: str
    license: str
    homepage: str
    repo: str  # GitHub "owner/name"
    kind: str  # "deb" (reuse upstream .deb) or "tarball" (we build the .deb)
    revision: int  # bump to rebuild the same upstream version
    assets: dict[str, str]  # arch -> upstream asset file name
    license_path: str = ""  # path of the licence file inside the upstream repo
    package: dict = field(default_factory=dict)  # control fields (tarball kind)
    companions: tuple[dict, ...] = ()  # empty transitional packages that depend on this one
    files: tuple[dict, ...] = ()  # kind "files": which upstream file goes where
    extra_assets: tuple[str, ...] = ()  # kind "files": more arch-independent assets (man pages...)
    note: str = ""  # one-line compatibility note shown on the landing page


def _need(data: dict, key: str, where: str):
    if key not in data or data[key] in ("", None):
        raise RecipeError(f"{where}: missing '{key}'")
    return data[key]


def parse_recipe(data: dict, where: str = "recipe") -> Recipe:
    name = str(_need(data, "name", where))
    source = data.get("source", {})
    if source.get("type", "github-release") != "github-release":
        raise RecipeError(f"{where}: only source.type = 'github-release' is supported")
    repo = str(_need(source, "repo", f"{where} [source]"))
    build = data.get("build", {})
    kind = str(_need(build, "kind", f"{where} [build]"))
    if kind not in KINDS:
        raise RecipeError(f"{where}: build.kind must be one of {KINDS}, got {kind!r}")
    assets = dict(_need(data, "assets", where))
    for arch in assets:
        if arch not in ARCHES:
            raise RecipeError(f"{where}: unsupported architecture {arch!r} (use {ARCHES})")
    package = dict(data.get("package", {}))
    if kind in ("tarball", "files"):
        for key in ("description", "section"):
            _need(package, key, f"{where} [package]")
    files = tuple(dict(f) for f in data.get("file", []))
    if kind == "files":
        if not files:
            raise RecipeError(f"{where}: kind 'files' needs at least one [[file]]")
        for f in files:
            _need(f, "src", f"{where} [[file]]")
            dest = str(_need(f, "dest", f"{where} [[file]]"))
            if not dest.startswith("/usr/") or ".." in Path(dest).parts:
                raise RecipeError(f"{where}: [[file]] dest must be an absolute path under /usr/: {dest!r}")
    elif files:
        raise RecipeError(f"{where}: [[file]] is only valid with kind 'files'")
    if "all" in assets and len(assets) != 1:
        raise RecipeError(f"{where}: assets.all cannot be mixed with per-architecture assets")
    companions = tuple(dict(c) for c in data.get("companion", []))
    for c in companions:
        for key in ("name", "description"):
            _need(c, key, f"{where} [[companion]]")
    return Recipe(
        companions=companions,
        files=files,
        extra_assets=tuple(build.get("extra_assets", ())),
        name=name,
        license=str(_need(data, "license", where)),
        homepage=str(data.get("homepage", f"https://github.com/{repo}")),
        note=str(data.get("note", "")).strip(),
        repo=repo,
        kind=kind,
        revision=int(build.get("revision", 1)),
        assets=assets,
        license_path=str(build.get("license_path", "")),
        package=package,
    )


def load_recipes(directory: Path, only: set[str] | None = None) -> list[Recipe]:
    recipes: list[Recipe] = []
    for path in sorted(Path(directory).glob("*.toml")):
        with path.open("rb") as fh:
            recipe = parse_recipe(tomllib.load(fh), where=path.name)
        if recipe.name != path.stem:
            raise RecipeError(f"{path.name}: 'name' must match the file name ({path.stem})")
        if only and recipe.name not in only:
            continue
        recipes.append(recipe)
    if only:
        missing = only - {r.name for r in recipes}
        if missing:
            raise RecipeError(f"unknown package(s): {', '.join(sorted(missing))}")
    return recipes
