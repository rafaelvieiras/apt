"""Publish: fetch upstream releases, build .debs, render indexes, sign, upload.

Upload order matters for clients that fetch while we publish:

1. new ``.deb`` files            (immutable, referenced by nothing yet)
2. ``by-hash`` index copies      (immutable)
3. ``Packages*`` and ``Release`` (reference only what is already uploaded)
4. ``InRelease`` / ``Release.gpg`` last, so no signed index ever points at a
   file that is not there yet
5. ``index.json`` / ``index.html`` / keys
6. cleanup of pruned pool files and old by-hash copies
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import debbuild, debversion, licenses, repo, sign, site, upstream
from .recipe import Recipe, load_recipes
from .storage import Storage


@dataclass
class Plan:
    recipe: Recipe
    tag: str
    version: str  # Debian version we will publish
    upstream_version: str
    reason: str


@dataclass
class Result:
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _expected_version(recipe: Recipe, release: upstream.Release) -> str | None:
    """Debian version for tarball recipes; ``None`` for upstream .debs (read after download)."""
    if recipe.kind == "tarball":
        return f"{debbuild.upstream_version(release.tag)}-{recipe.revision}"
    return None


def plan_package(recipe: Recipe, state: dict, release: upstream.Release) -> tuple[Plan | None, str]:
    """Decide whether ``recipe`` needs publishing. Returns (plan, human reason)."""
    entry = state["packages"].get(recipe.name, {})
    known = entry.get("versions", {})
    up = debbuild.upstream_version(release.tag)
    newest = repo.newest_upstream(entry)
    if newest and debversion.compare(up, newest) < 0:
        return None, f"upstream {up} is older than published {newest}; never going backwards"
    expected = _expected_version(recipe, release)
    if expected and expected in known:
        return None, f"{expected} already published"
    if not expected and any(v.get("upstream_version") == up for v in known.values()):
        return None, f"upstream {up} already published"
    return Plan(recipe, release.tag, expected or up, up, f"new upstream {up}"), "needs build"


def _build(plan: Plan, release: upstream.Release, workdir: Path) -> dict[str, tuple[Path, str]]:
    """Download and build every architecture. Returns arch -> (deb path, version)."""
    recipe = plan.recipe
    licenses.check(recipe.license)
    built: dict[str, tuple[Path, str]] = {}
    license_text = ""
    if recipe.kind == "tarball":
        if not recipe.license_path:
            raise debbuild.BuildError(f"{recipe.name}: build.license_path is required for tarball recipes")
        license_text = upstream.fetch_text(
            f"https://raw.githubusercontent.com/{recipe.repo}/{release.tag}/{recipe.license_path}"
        )
    epoch = _epoch(release.published)
    for arch, asset_name in recipe.assets.items():
        asset = release.assets.get(asset_name)
        if asset is None:
            raise debbuild.BuildError(f"{recipe.name}: release {release.tag} has no asset {asset_name!r}")
        raw = workdir / f"dl-{arch}-{asset_name}"
        upstream.download(asset, raw)
        if recipe.kind == "deb":
            deb, version = debbuild.adopt_deb(recipe, arch, raw, workdir / "out")
        else:
            deb = debbuild.build_from_tarball(
                recipe, arch, debbuild.upstream_version(release.tag), raw, license_text,
                workdir / "out", epoch,
            )
            version = plan.version
        built[arch] = (deb, version)
    versions = {v for _, v in built.values()}
    if len(versions) != 1:
        raise debbuild.BuildError(f"{recipe.name}: architectures disagree on version: {sorted(versions)}")
    return built


def _epoch(published: str) -> int:
    try:
        return int(datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _synopsis_only(control: str) -> str:
    """Keep the control stanza but cut a multi-line Description down to its synopsis."""
    out: list[str] = []
    in_description = False
    for line in control.splitlines():
        if line.startswith("Description:"):
            in_description = True
            out.append(line)
        elif in_description and line.startswith((" ", "\t")):
            continue
        else:
            in_description = False
            out.append(line)
    return "\n".join(out)


def publish(
    cfg: repo.RepoConfig,
    recipes_dir: Path,
    storage: Storage,
    *,
    private_key: str | None,
    passphrase: str | None,
    only: set[str] | None = None,
    force_index: bool = False,
    dry_run: bool = False,
    log=print,
    now: float | None = None,
    key_path: Path | None = None,
) -> Result:
    result = Result()
    state = repo.load_state(storage.get("index.json"))
    recipes = load_recipes(recipes_dir, only)
    uploads: list[tuple[str, Path]] = []
    changed = False

    with tempfile.TemporaryDirectory(prefix="aptrepo-work-") as tmp:
        work = Path(tmp)
        for recipe in recipes:
            try:
                release = upstream.latest_release(recipe.repo)
                plan, reason = plan_package(recipe, state, release)
                if plan is None:
                    log(f"= {recipe.name}: {reason}")
                    result.skipped.append(recipe.name)
                    continue
                log(f"+ {recipe.name}: {plan.reason}")
                if dry_run:
                    result.published.append(recipe.name)
                    continue
                built = _build(plan, release, work / recipe.name)
                version = next(iter(built.values()))[1]
                epoch = _epoch(release.published)
                groups: dict[str, dict[str, Path]] = {recipe.name: {a: d for a, (d, _) in built.items()}}
                for spec in recipe.companions:
                    groups[spec["name"]] = {
                        arch: debbuild.build_companion(recipe, spec, arch, version, work / recipe.name / "out", epoch)
                        for arch in built
                    }
                for pkg_name, debs in groups.items():
                    arches: dict[str, dict] = {}
                    for arch, deb in debs.items():
                        key = debbuild.pool_path(pkg_name, version, arch)
                        arches[arch] = {
                            "filename": key,
                            "control": _synopsis_only(debbuild.control_text(deb)),
                            **debbuild.hashes(deb),
                        }
                        uploads.append((key, deb))
                    repo.add_version(
                        state,
                        name=pkg_name,
                        homepage=recipe.homepage,
                        license=recipe.license,
                        version=version,
                        upstream_version=plan.upstream_version,
                        source=f"https://github.com/{recipe.repo}/releases/tag/{release.tag}",
                        released=release.published,
                        arches=arches,
                    )
                changed = True
                result.published.append(recipe.name)
            except (upstream.UpstreamError, debbuild.BuildError, licenses.LicenseError) as exc:
                log(f"! {recipe.name}: {exc}")
                result.errors.append(f"{recipe.name}: {exc}")

        if dry_run:
            return result
        if not changed and not force_index:
            log("nothing to publish")
            return result
        if not private_key:
            raise sign.SignError("no signing key: set APT_GPG_PRIVATE_KEY")

        doomed = repo.prune(state, cfg.retain)
        state["generated"] = datetime.fromtimestamp(now or _now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rendered = repo.render_dists(state, cfg, now=now)

        public = (key_path or Path(cfg.key_file)).read_bytes()
        with sign.Signer(private_key, passphrase) as signer:
            signer_fingerprint = signer.fingerprint
            if sign.public_fingerprint(public) != signer.fingerprint:
                raise sign.SignError("signing key does not match the published public key")
            in_release = signer.clearsign(rendered.release)
            release_gpg = signer.detach_sign(rendered.release)
        base = f"dists/{cfg.suite}"

        for key, path in uploads:
            storage.put_file(key, path)
        for key, data in rendered.byhash.items():
            storage.put(key, data)
        for key, data in rendered.files.items():
            storage.put(key, data)
        storage.put(f"{base}/InRelease", in_release)
        storage.put(f"{base}/Release.gpg", release_gpg)

        storage.put("key.asc", public)
        storage.put("key.gpg", sign.dearmor(public))
        fingerprint = signer_fingerprint
        old_current = state["byhash"]["current"]
        old_previous = state["byhash"]["previous"]
        state["byhash"] = {"current": sorted(rendered.byhash), "previous": old_current}
        storage.put("index.json", (json.dumps(state, indent=1, sort_keys=True) + "\n").encode())
        storage.put("index.html", site.render(state, cfg, fingerprint).encode())

        # Content-addressed: a key can be in several generations. Keep this one and
        # the one before it (clients mid-update may still ask for it), drop the rest.
        keep = set(state["byhash"]["current"]) | set(old_current)
        for key in sorted(set(old_previous) - keep):
            storage.delete(key)
        for key in doomed:
            storage.delete(key)
    return result


def _now() -> float:
    import time

    return time.time()
