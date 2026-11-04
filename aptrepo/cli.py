"""Command line: ``python -m aptrepo <command>``."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

from . import publish as publisher
from . import recipe, repo, storage, upstream
from . import site as sitebuild

ROOT = Path(__file__).resolve().parent.parent


def _config(path: str) -> repo.RepoConfig:
    with open(path, "rb") as fh:
        return repo.RepoConfig.from_toml(tomllib.load(fh))


def cmd_check(args: argparse.Namespace) -> int:
    """Validate recipes and the licence gate without touching the network."""
    from . import licenses

    failures = 0
    for r in recipe.load_recipes(Path(args.recipes)):
        try:
            licenses.check(r.license)
            print(f"ok  {r.name}  ({r.kind}, {', '.join(sorted(r.assets))}, {r.license})")
        except licenses.LicenseError as exc:
            failures += 1
            print(f"ERR {r.name}: {exc}")
    return 1 if failures else 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Show what a publish would do."""
    store = storage.open_storage(args.storage)
    state = repo.load_state(store.get("index.json"))
    pending = 0
    for r in recipe.load_recipes(Path(args.recipes), set(args.package) or None):
        release = upstream.latest_release(r.repo)
        plan, reason = publisher.plan_package(r, state, release)
        print(f"{'+' if plan else '='} {r.name}: {reason}")
        pending += bool(plan)
    return 0 if not args.exit_code else (2 if pending else 0)


def cmd_publish(args: argparse.Namespace) -> int:
    cfg = _config(args.config)
    store = storage.open_storage(args.storage)
    result = publisher.publish(
        cfg,
        Path(args.recipes),
        store,
        private_key=os.environ.get("APT_GPG_PRIVATE_KEY"),
        passphrase=os.environ.get("APT_GPG_PASSPHRASE"),
        only=set(args.package) or None,
        force_index=args.force_index,
        dry_run=args.dry_run,
    )
    print(
        f"published={len(result.published)} skipped={len(result.skipped)} errors={len(result.errors)}"
    )
    # A failing package must not block the others, but the run still has to go red.
    return 1 if result.errors else 0


def _export(args: argparse.Namespace, store: storage.Storage, cfg: repo.RepoConfig) -> Path:
    out = Path(args.out)
    data = sitebuild.export_from_storage(
        store, cfg, ROOT / cfg.key_file, out, index=Path(args.index) if args.index else None
    )
    print(f"wrote {out} ({len(data['packages'])} packages)")
    return out


def cmd_site_data(args: argparse.Namespace) -> int:
    """Write site-data.json (the Astro build input) from the published index.json."""
    cfg = _config(args.config)
    _export(args, storage.open_storage(args.storage), cfg)
    return 0


def cmd_upload_site(args: argparse.Namespace) -> int:
    """Upload an already built site/dist/ (no Node needed)."""
    sitebuild.upload(storage.open_storage(args.storage), Path(args.dist))
    return 0


def cmd_publish_site(args: argparse.Namespace) -> int:
    """Export data, build the Astro site (npm ci && npm run build) and upload it."""
    cfg = _config(args.config)
    store = storage.open_storage(args.storage)
    out = _export(args, store, cfg)
    dist = sitebuild.build(ROOT / "site", data=out)
    sitebuild.upload(store, dist)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aptrepo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, with_config: bool = False) -> None:
        p.add_argument("--recipes", default=str(ROOT / "packages"))
        p.add_argument("--storage", default="r2", help="'r2' or 'dir:PATH'")
        p.add_argument("package", nargs="*", help="limit to these packages")
        if with_config:
            p.add_argument("--config", default=str(ROOT / "repo.toml"))

    p_check = sub.add_parser("check", help="validate recipes and licences (offline)")
    p_check.add_argument("--recipes", default=str(ROOT / "packages"))
    p_check.set_defaults(func=cmd_check)

    p_plan = sub.add_parser("plan", help="show what would be published")
    common(p_plan)
    p_plan.add_argument("--exit-code", action="store_true", help="exit 2 when work is pending")
    p_plan.set_defaults(func=cmd_plan)

    p_pub = sub.add_parser("publish", help="build, sign and upload")
    common(p_pub, with_config=True)
    p_pub.add_argument("--dry-run", action="store_true")
    p_pub.add_argument("--force-index", action="store_true", help="re-render and re-sign even if nothing changed")
    p_pub.set_defaults(func=cmd_publish)

    default_out = str(ROOT / sitebuild.DATA_PATH)

    def site_data_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--storage", default="r2", help="'r2' or 'dir:PATH'; index.json is read from here")
        p.add_argument("--config", default=str(ROOT / "repo.toml"))
        p.add_argument("--index", help="read this local index.json instead of the storage")
        p.add_argument("--out", default=default_out, help="where to write site-data.json")

    p_data = sub.add_parser("site-data", help="export site-data.json for the Astro site")
    site_data_args(p_data)
    p_data.set_defaults(func=cmd_site_data)

    p_up = sub.add_parser("upload-site", help="upload a built site/dist/ (refuses apt paths)")
    p_up.add_argument("dist", help="build output, normally site/dist")
    p_up.add_argument("--storage", default="r2", help="'r2' or 'dir:PATH'")
    p_up.set_defaults(func=cmd_upload_site)

    p_site = sub.add_parser("publish-site", help="export data, build the site with npm and upload it")
    site_data_args(p_site)
    p_site.set_defaults(func=cmd_publish_site)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError, recipe.RecipeError, upstream.UpstreamError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
