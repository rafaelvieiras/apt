"""Offline tests. Upstream is faked, GnuPG and dpkg-deb are real."""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aptrepo import debbuild, debversion, licenses, publish, recipe, repo, sign, site, storage, upstream

ROOT = Path(__file__).resolve().parent.parent


def make_key(home: Path) -> tuple[str, bytes]:
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    base = ["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback", "--passphrase", ""]
    subprocess.run(base + ["--quick-generate-key", "t <t@example.invalid>", "ed25519", "sign", "never"],
                   check=True, capture_output=True)
    sec = subprocess.run(base + ["--armor", "--export-secret-keys"], check=True, capture_output=True).stdout
    pub = subprocess.run(base + ["--armor", "--export"], check=True, capture_output=True).stdout
    return sec.decode(), pub


def make_tarball(path: Path, top: str = "tool-linux-x86_64") -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data, mode in [
            (f"{top}/bin/tool", b"#!/bin/sh\necho tool\n", 0o755),
            (f"{top}/share/tool/runtime.txt", b"runtime\n", 0o644),
        ]:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))


CFG = repo.RepoConfig(
    origin="Test", label="Test", suite="stable", component="main", architectures=["amd64", "arm64"],
    base_url="https://apt.example.test", description="d", key_file="unused", key_name="k",
)


class DebVersion(unittest.TestCase):
    def test_matches_dpkg(self):
        values = ["1.0", "1.0-1", "1.0~rc1", "1:0.5", "0.12.6-1", "0.12.5-1~noble", "26.9.1-1",
                  "1.0+b1", "1.0a", "1.00", "10.0", "9.9", "1.0-1ubuntu1"]
        for a in values:
            for b in values:
                lt = subprocess.run(["dpkg", "--compare-versions", a, "lt", b]).returncode == 0
                eq = subprocess.run(["dpkg", "--compare-versions", a, "eq", b]).returncode == 0
                self.assertEqual(debversion.compare(a, b), -1 if lt else (0 if eq else 1), (a, b))


class Licenses(unittest.TestCase):
    def test_allows_spdx_expression(self):
        licenses.check("Apache-2.0 AND Vim")
        licenses.check("MIT")

    def test_fails_closed(self):
        for bad in ("Proprietary", "MIT AND SSPL-1.0", "", "BUSL-1.1"):
            with self.assertRaises(licenses.LicenseError, msg=bad):
                licenses.check(bad)


class Recipes(unittest.TestCase):
    def test_shipped_recipes_are_valid(self):
        recipes = recipe.load_recipes(ROOT / "packages")
        self.assertTrue(recipes)
        for r in recipes:
            licenses.check(r.license)

    def test_rejects_bad_input(self):
        base = {"name": "x", "license": "MIT", "source": {"repo": "a/b"}, "build": {"kind": "deb"},
                "assets": {"amd64": "x.deb"}}
        recipe.parse_recipe(base)
        for patch in ({"assets": {"riscv": "x"}}, {"build": {"kind": "magic"}}, {"source": {}}):
            with self.assertRaises(recipe.RecipeError):
                recipe.parse_recipe({**base, **patch})
        with self.assertRaises(recipe.RecipeError):  # tarball needs a description
            recipe.parse_recipe({**base, "build": {"kind": "tarball"}})


class Index(unittest.TestCase):
    def state(self):
        s = repo.empty_state()
        for ver, up in (("1.0-1", "1.0"), ("1.1-1", "1.1")):
            repo.add_version(
                s, name="tool", homepage="https://x", license="MIT", version=ver, upstream_version=up,
                source="https://x/r", released="2026-01-01T00:00:00Z",
                arches={a: {"filename": f"pool/main/t/tool/tool_{ver}_{a}.deb", "size": 3, "md5": "m",
                            "sha1": "s", "sha256": "h",
                            "control": f"Package: tool\nVersion: {ver}\nArchitecture: {a}\nDescription: A tool"}
                        for a in ("amd64", "arm64")},
            )
        return s

    def test_packages_lists_newest_first_per_arch(self):
        text = repo.render_packages(self.state(), "amd64").decode()
        self.assertLess(text.index("Version: 1.1-1"), text.index("Version: 1.0-1"))
        self.assertIn("Filename: pool/main/t/tool/tool_1.1-1_amd64.deb", text)
        self.assertNotIn("arm64.deb", text)

    def test_release_hashes_match_files_and_by_hash(self):
        out = repo.render_dists(self.state(), CFG, now=0)
        release = out.release.decode()
        self.assertIn("Acquire-By-Hash: yes", release)
        self.assertIn("Suite: stable", release)
        for key, data in out.files.items():
            rel = key.removeprefix("dists/stable/")
            if rel in ("Release",):
                continue
            import hashlib
            self.assertIn(f" {hashlib.sha256(data).hexdigest()} ", release, rel)
        for key, data in out.byhash.items():
            import hashlib
            self.assertTrue(key.endswith(hashlib.sha256(data).hexdigest()))

    def test_prune_keeps_newest(self):
        s = self.state()
        doomed = repo.prune(s, 1)
        self.assertEqual(list(s["packages"]["tool"]["versions"]), ["1.1-1"])
        self.assertEqual(len(doomed), 2)

    def test_render_is_deterministic(self):
        a = repo.render_dists(self.state(), CFG, now=0)
        b = repo.render_dists(self.state(), CFG, now=0)
        self.assertEqual(a.files, b.files)


class CachePolicy(unittest.TestCase):
    def test_immutable_vs_short(self):
        for key in ("pool/main/t/tool/tool_1_amd64.deb",
                    "dists/stable/main/binary-amd64/by-hash/SHA256/abc"):
            self.assertEqual(storage.cache_control(key), storage.IMMUTABLE, key)
        for key in ("index.json", "dists/stable/InRelease", "dists/stable/Release",
                    "dists/stable/main/binary-amd64/Packages.xz", "key.gpg", "index.html"):
            self.assertEqual(storage.cache_control(key), storage.SHORT, key)

    def test_site_assets_are_immutable_pages_are_short(self):
        self.assertEqual(storage.cache_control("_astro/index.3f9a1c.css"), storage.IMMUTABLE)
        self.assertEqual(storage.cache_control("_astro/behavior.8b2d.js"), storage.IMMUTABLE)
        for key in ("index.html", "packages", "packages.html", "robots.txt", "favicon.svg", "favicon.ico"):
            self.assertEqual(storage.cache_control(key), storage.SHORT, key)

    def test_content_types_do_not_depend_on_the_machine(self):
        expected = {
            "index.html": "text/html; charset=utf-8",
            "packages.html": "text/html; charset=utf-8",
            "_astro/a.css": "text/css; charset=utf-8",
            "_astro/a.js": "text/javascript; charset=utf-8",
            "favicon.svg": "image/svg+xml",
            "favicon.ico": "image/x-icon",
            "robots.txt": "text/plain; charset=utf-8",
            "index.json": "application/json",
            "key.asc": "text/plain; charset=utf-8",
            "dists/stable/InRelease": "text/plain; charset=utf-8",
            "pool/main/t/tool/tool_1_amd64.deb": "application/vnd.debian.binary-package",
            "dists/stable/main/binary-amd64/Packages.xz": "application/octet-stream",
            "something.unknown": "application/octet-stream",
        }
        for key, ctype in expected.items():
            self.assertEqual(storage.content_type(key), ctype, key)

    def test_dir_storage_records_explicit_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = storage.DirStorage(Path(tmp))
            store.put("packages", b"<html>", "text/html; charset=utf-8")
            store.put("other", b"x")
            self.assertEqual(store.types["packages"], "text/html; charset=utf-8")
            self.assertEqual(store.types["other"], "application/octet-stream")

    def test_dir_storage_blocks_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                storage.DirStorage(Path(tmp)).put("../evil", b"x")


class Signing(unittest.TestCase):
    def test_clearsign_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            sec, pub = make_key(Path(tmp))
            with sign.Signer(sec) as signer:
                signed = signer.clearsign(b"Suite: stable\n")
            sign.verify_clearsigned(pub, signed)
            with self.assertRaises(sign.SignError):
                sign.verify_clearsigned(pub, signed.replace(b"stable", b"evil"))


class Build(unittest.TestCase):
    def test_tarball_deb_is_valid_and_reproducible(self):
        r = recipe.parse_recipe({
            "name": "tool", "license": "MIT", "source": {"repo": "a/b"},
            "build": {"kind": "tarball", "revision": 2, "license_path": "L"},
            "assets": {"amd64": "t.tgz"},
            "package": {"section": "utils", "description": "Short\nLong line one\n.\nLong line two",
                        "depends": "libc6", "replaces": "tool-runtime (<< {deb_version})"},
        })
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tgz = tmp / "t.tgz"
            make_tarball(tgz)
            debs = [debbuild.build_from_tarball(r, "amd64", "1.2.3", tgz, "MIT text", tmp / f"o{i}", 1_700_000_000)
                    for i in range(2)]
            self.assertEqual(debs[0].name, "tool_1.2.3-2_amd64.deb")
            self.assertEqual(debs[0].read_bytes(), debs[1].read_bytes(), "build must be reproducible")
            self.assertEqual(debbuild.control_field(debs[0], "Version"), "1.2.3-2")
            self.assertEqual(debbuild.control_field(debs[0], "Replaces"), "tool-runtime (<< 1.2.3-2)")
            listing = subprocess.run(["dpkg-deb", "-c", str(debs[0])], capture_output=True, text=True).stdout
            self.assertIn("./usr/bin/tool", listing)
            self.assertIn("./usr/share/doc/tool/copyright", listing)
            self.assertNotIn("tool-linux-x86_64", listing, "top-level dir must be stripped")
            self.assertTrue(all("root/root" in line for line in listing.splitlines()))

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tgz = tmp / "evil.tgz"
            with tarfile.open(tgz, "w:gz") as tar:
                info = tarfile.TarInfo("top/../../escape")
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(Exception):
                debbuild._extract(tgz, tmp / "dest")


def files_recipe(**over):
    data = {
        "name": "tool", "license": "MIT", "source": {"repo": "a/b"},
        "build": {"kind": "files", "license_path": "L", "revision": 2},
        "assets": {"amd64": "tool-*-amd64.tar.gz"},
        "file": [
            {"src": "*/bin/tool", "dest": "/usr/bin/tool"},
            {"src": "*/man/*.1", "dest": "/usr/share/man/man1/", "gzip": True},
            {"src": "*/comp/tool.bash", "dest": "/usr/share/bash-completion/completions/tool"},
        ],
        "package": {"section": "utils", "description": "Short\nLong", "depends": "python3 (>= 3.11)"},
    }
    data.update(over)
    return recipe.parse_recipe(data)


def make_files_tarball(path: Path) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in [("tool-1/bin/tool", b"#!/bin/sh\n"), ("tool-1/man/tool.1", b".TH TOOL\n"),
                           ("tool-1/man/tool-add.1", b".TH ADD\n"), ("tool-1/comp/tool.bash", b"# c\n"),
                           ("tool-1/README", b"readme\n")]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class FilesKind(unittest.TestCase):
    def build(self, rec, tmp, assets=None, epoch=1_700_000_000):
        tgz = tmp / "tool-1-amd64.tar.gz"
        make_files_tarball(tgz)
        return debbuild.build_from_files(rec, "amd64", "1.0", assets or {"tool-*-amd64.tar.gz": (tgz.name, tgz)},
                                         "MIT text", tmp / "out", epoch)

    def test_places_files_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            a = self.build(files_recipe(), tmp)
            data = a.read_bytes()
            b = self.build(files_recipe(), tmp)
            self.assertEqual(data, b.read_bytes(), "must be reproducible")
            self.assertEqual(a.name, "tool_1.0-2_amd64.deb")
            listing = subprocess.run(["dpkg-deb", "-c", str(a)], capture_output=True, text=True).stdout
            for want in ("./usr/bin/tool", "./usr/share/man/man1/tool.1.gz", "./usr/share/man/man1/tool-add.1.gz",
                         "./usr/share/bash-completion/completions/tool", "./usr/share/doc/tool/copyright"):
                self.assertIn(want, listing)
            self.assertNotIn("README", listing, "only listed files may be shipped")
            bin_line = next(l for l in listing.splitlines() if l.endswith("usr/bin/tool"))
            self.assertTrue(bin_line.startswith("-rwxr-xr-x"), bin_line)
            self.assertEqual(debbuild.control_field(a, "Depends"), "python3 (>= 3.11)")

    def test_glob_must_match_exactly_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = files_recipe(file=[{"src": "*/man/*.1", "dest": "/usr/share/man/man1/tool.1"}])
            with self.assertRaises(debbuild.BuildError):
                self.build(rec, Path(tmp))
            rec = files_recipe(file=[{"src": "*/nothing", "dest": "/usr/bin/tool"}])
            with self.assertRaises(debbuild.BuildError):
                self.build(rec, Path(tmp))

    def test_second_asset_via_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tgz = tmp / "x.tar.gz"
            make_files_tarball(tgz)
            script = tmp / "tool"
            script.write_text("#!/usr/bin/env python3\n")
            rec = files_recipe(
                assets={"all": "tool"},
                file=[{"src": "tool", "dest": "/usr/bin/tool"},
                      {"from": "x.tar.gz", "src": "tool-1/man/tool.1", "dest": "/usr/share/man/man1/tool.1"}],
            )
            deb = debbuild.build_from_files(rec, "all", "1.0", {"tool": ("tool", script), "x.tar.gz": ("x.tar.gz", tgz)},
                                            "L", tmp / "out", 0)
            self.assertEqual(deb.name, "tool_1.0-2_all.deb")
            self.assertEqual(debbuild.control_field(deb, "Architecture"), "all")

    def test_recipe_validation(self):
        with self.assertRaises(recipe.RecipeError):
            files_recipe(file=[])
        with self.assertRaises(recipe.RecipeError):
            files_recipe(file=[{"src": "x", "dest": "/etc/passwd"}])  # outside /usr
        with self.assertRaises(recipe.RecipeError):
            files_recipe(file=[{"src": "x", "dest": "/usr/../etc/x"}])
        with self.assertRaises(recipe.RecipeError):
            files_recipe(assets={"all": "a", "amd64": "b"})

    def test_find_asset_glob(self):
        mk = lambda n: upstream.Asset(n, "u", 1, None)
        rel = upstream.Release("v1", "", {n: mk(n) for n in ("a_24.04.deb", "a_26.04.deb", "b.txt")})
        self.assertEqual(upstream.find_asset(rel, "b.txt").name, "b.txt")
        self.assertEqual(upstream.find_asset(rel, "a_24*.deb").name, "a_24.04.deb")
        with self.assertRaises(upstream.UpstreamError):
            upstream.find_asset(rel, "a_*.deb")  # ambiguous
        with self.assertRaises(upstream.UpstreamError):
            upstream.find_asset(rel, "zzz*")

    def test_tag_with_dashes_becomes_a_valid_version(self):
        self.assertEqual(debbuild.upstream_version("1.3.1-0-ppa2"), "1.3.1.0.ppa2")
        self.assertEqual(debbuild.upstream_version("v2026.10.26"), "2026.10.26")


class AdoptDeb(unittest.TestCase):
    def test_dependency_override_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "r"
            (root / "DEBIAN").mkdir(parents=True)
            (root / "usr/bin").mkdir(parents=True)
            (root / "usr/bin/x").write_text("x")
            (root / "DEBIAN/control").write_text(
                "Package: x\nVersion: 1.0-1\nArchitecture: amd64\nMaintainer: m\nDepends: libc6\n"
                "Provides: x-terminal-emulator\nDescription: d\n long\n")
            src = tmp / "x.deb"
            subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(root), str(src)], check=True, capture_output=True)
            rec = recipe.parse_recipe({"name": "x", "license": "MIT", "source": {"repo": "a/b"},
                                       "build": {"kind": "deb"}, "assets": {"amd64": "x.deb"},
                                       "package": {"depends": "libc6 (>= 2.38)"}})
            out, version = debbuild.adopt_deb(rec, "amd64", src, tmp / "pool", 0)
            self.assertEqual(version, "1.0-1")
            self.assertEqual(debbuild.control_field(out, "Depends"), "libc6 (>= 2.38)")
            self.assertEqual(debbuild.control_field(out, "Provides"), "x-terminal-emulator")
            self.assertEqual(debbuild.control_field(out, "Description").splitlines()[0], "d")
            self.assertIn("./usr/bin/x", subprocess.run(["dpkg-deb", "-c", str(out)], capture_output=True, text=True).stdout)


class ArchAll(unittest.TestCase):
    def test_all_package_is_listed_in_every_architecture(self):
        s = repo.empty_state()
        repo.add_version(
            s, name="tool", homepage="h", license="MIT", version="1-1", upstream_version="1", source="s",
            released="", arches={"all": {"filename": "pool/main/t/tool/tool_1-1_all.deb", "size": 1, "md5": "m",
                                         "sha1": "s", "sha256": "h",
                                         "control": "Package: tool\nVersion: 1-1\nArchitecture: all\nDescription: d"}})
        for arch in ("amd64", "arm64"):
            self.assertIn("tool_1-1_all.deb", repo.render_packages(s, arch).decode())


class SiteExport(unittest.TestCase):
    FP = "A1B2C3D4E5F60718293A4B5C6D7E8F9012345678"

    def state(self, **over):
        s = repo.empty_state()
        s["generated"] = "2026-05-20T06:17:03Z"
        for name, kw in {
            "alpha": {"note": "Needs glibc 2.38 or newer."},
            "beta": {},
            "beta-runtime": {"desc": "Transitional package for beta"},
        }.items():
            kw = {**kw, **over.get(name, {})}
            repo.add_version(
                s, name=name, homepage=kw.get("homepage", f"https://example.test/{name}"), license="MIT",
                version=kw.get("version", "1.2.3-1"), upstream_version="1.2.3", source="https://x/r",
                released="2026-05-19T10:00:00Z",
                arches={a: {"filename": "f", "size": 1, "md5": "", "sha1": "", "sha256": "",
                            "control": f"Package: {name}\nDescription: {kw.get('desc', 'Does things')}"}
                        for a in kw.get("arches", ("amd64", "arm64"))},
                note=kw.get("note", ""),
            )
        return s

    def export(self, state=None, cfg=CFG, fp=FP, now=1_779_000_000):
        return site.export(state or self.state(), cfg, fp, now=now)

    def test_schema_and_repo_config(self):
        data = self.export()
        self.assertEqual(set(data), {"schema", "generated", "indexGenerated", "repo", "fingerprint", "packages"})
        self.assertEqual(data["repo"]["baseUrl"], CFG.base_url)
        self.assertEqual((data["repo"]["suite"], data["repo"]["component"]), ("stable", "main"))
        self.assertEqual(data["repo"]["architectures"], ["amd64", "arm64"])
        self.assertEqual(data["indexGenerated"], "2026-05-20T06:17:03Z")
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_generated_is_a_real_utc_timestamp(self):
        # Regression: the old page rendered an empty "Generated" because state["generated"] was unset.
        state = repo.empty_state()
        self.assertEqual(self.export(state, now=0)["generated"], "1970-01-01T00:00:00Z")
        self.assertRegex(site.export(state, CFG, self.FP)["generated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_fingerprint_is_raw_and_pretty(self):
        fp = self.export()["fingerprint"]
        self.assertEqual(fp["raw"], self.FP)
        self.assertEqual(fp["pretty"], "A1B2 C3D4 E5F6 0718 293A  4B5C 6D7E 8F90 1234 5678")
        self.assertEqual(fp["pretty"].replace(" ", ""), self.FP)

    def test_packages_are_sorted_with_newest_version(self):
        state = self.state()
        repo.add_version(
            state, name="alpha", homepage="https://example.test/alpha", license="MIT", version="1.10.0-1",
            upstream_version="1.10.0", source="s", released="2026-05-21T00:00:00Z",
            arches={"amd64": {"control": "Description: Does things"}},
        )
        packages = self.export(state)["packages"]
        self.assertEqual([p["name"] for p in packages], ["alpha", "beta", "beta-runtime"])
        alpha = packages[0]
        self.assertEqual((alpha["version"], alpha["debVersion"]), ("1.10.0", "1.10.0-1"))
        self.assertEqual(alpha["arches"], ["amd64"])
        self.assertEqual(alpha["released"], "2026-05-21T00:00:00Z")
        self.assertEqual(packages[1]["arches"], ["amd64", "arm64"])
        self.assertEqual(alpha["description"], "Does things")
        self.assertEqual(alpha["license"], "MIT")
        self.assertEqual(alpha["homepage"], "https://example.test/alpha")

    def test_note_is_kept_and_optional(self):
        packages = {p["name"]: p for p in self.export()["packages"]}
        self.assertEqual(packages["alpha"]["note"], "Needs glibc 2.38 or newer.")
        self.assertEqual(packages["beta"]["note"], "")

    def test_old_state_without_notes_or_released_still_exports(self):
        state = self.state()
        for entry in state["packages"].values():
            entry.pop("note", None)
            for info in entry["versions"].values():
                info.pop("released", None)
                info.pop("upstream_version", None)
        packages = self.export(state)["packages"]
        self.assertTrue(all(p["note"] == "" and p["released"] == "" for p in packages))
        self.assertEqual(packages[0]["version"], "1.2.3-1")  # falls back to the Debian version
        self.assertEqual(self.export(repo.empty_state())["packages"], [])

    def test_transitional_detection(self):
        packages = {p["name"]: p for p in self.export()["packages"]}
        self.assertEqual({n: p["transitional"] for n, p in packages.items()},
                         {"alpha": False, "beta": False, "beta-runtime": True})

    def test_entries_without_versions_are_skipped(self):
        state = self.state()
        state["packages"]["ghost"] = {"versions": {}}
        self.assertNotIn("ghost", [p["name"] for p in self.export(state)["packages"]])

    def test_hostile_values_stay_valid_json_and_links_are_http_only(self):
        evil = '"><script>alert(1)</script>\u2028\n\\'
        state = self.state(alpha={"homepage": "javascript:alert(1)", "note": evil, "desc": evil})
        cfg = repo.RepoConfig(**{**CFG.__dict__, "origin": evil, "description": evil})
        data = self.export(state, cfg, "AB" + evil)
        text = json.dumps(data, ensure_ascii=False)
        self.assertEqual(json.loads(text), data)
        alpha = data["packages"][0]
        self.assertEqual(alpha["homepage"], "")  # javascript: never reaches an href
        self.assertEqual(alpha["note"], evil)  # escaping is the template's job (Astro does it)

    def test_write_data_round_trips_and_ends_with_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "deep" / "site-data.json"
            data = self.export()
            site.write_data(out, data)
            self.assertEqual(json.loads(out.read_text()), data)
            self.assertTrue(out.read_text().endswith("\n"))

    def test_export_from_storage_uses_the_real_key_and_needs_an_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _, pub = make_key(tmp / "gnupg")
            key = tmp / "pub.asc"
            key.write_bytes(pub)
            store = storage.DirStorage(tmp / "bucket")
            out = tmp / "out.json"
            with self.assertRaises(site.SiteError):
                site.export_from_storage(store, CFG, key, out)
            store.put("index.json", json.dumps(self.state()).encode())
            data = site.export_from_storage(store, CFG, key, out)
            self.assertEqual(data["fingerprint"]["raw"], sign.public_fingerprint(pub))
            self.assertEqual(json.loads(out.read_text())["packages"][0]["name"], "alpha")


class SiteUpload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name) / "dist"
        self.store = storage.DirStorage(Path(self.tmp.name) / "bucket")

    def make(self, files):
        for key, data in files.items():
            path = self.dist / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def basic(self, **more):
        self.make({"index.html": b"<h1>home", "packages.html": b"<h1>pkgs", "favicon.svg": b"<svg/>", **more})

    def test_pages_get_an_extensionless_copy_with_html_content_type(self):
        self.basic()
        site.upload(self.store, self.dist, log=lambda *_: None)
        self.assertEqual(self.store.get("packages"), b"<h1>pkgs")
        self.assertEqual(self.store.get("packages.html"), b"<h1>pkgs")
        self.assertEqual(self.store.types["packages"], "text/html; charset=utf-8")
        self.assertEqual(self.store.types["packages.html"], "text/html; charset=utf-8")
        self.assertEqual(self.store.types["index.html"], "text/html; charset=utf-8")
        self.assertFalse(self.store.exists("index"), "the home page is served by the / rewrite only")

    def test_any_other_html_page_gets_the_same_treatment(self):
        self.basic(**{"about.html": b"about", "docs/guide.html": b"guide"})
        site.upload(self.store, self.dist, log=lambda *_: None)
        for key in ("about", "about.html", "docs/guide", "docs/guide.html"):
            self.assertTrue(self.store.exists(key), key)
            self.assertEqual(self.store.types[key], "text/html; charset=utf-8", key)

    def test_cache_headers_and_content_types(self):
        self.basic(**{"_astro/app.abc123.css": b"a{}", "_astro/app.abc123.js": b"1", "robots.txt": b"x"})
        site.upload(self.store, self.dist, log=lambda *_: None)
        h, t = self.store.headers, self.store.types
        self.assertEqual(h["_astro/app.abc123.css"], storage.IMMUTABLE)
        self.assertEqual(h["_astro/app.abc123.js"], storage.IMMUTABLE)
        for key in ("index.html", "packages", "packages.html", "favicon.svg", "robots.txt"):
            self.assertEqual(h[key], storage.SHORT, key)
        self.assertEqual(t["_astro/app.abc123.css"], "text/css; charset=utf-8")
        self.assertEqual(t["_astro/app.abc123.js"], "text/javascript; charset=utf-8")
        self.assertEqual(t["favicon.svg"], "image/svg+xml")

    def test_home_page_goes_last(self):
        self.basic(**{"_astro/a.css": b"a{}"})
        keys = site.upload(self.store, self.dist, log=lambda *_: None)
        self.assertEqual(keys[-1], "index.html")
        self.assertLess(keys.index("_astro/a.css"), keys.index("packages"))

    def test_refuses_keys_that_could_shadow_apt_paths(self):
        for bad in ("dists/stable/InRelease", "pool/main/x.deb", "key.gpg", "key.asc", "key.txt",
                    "index.json", "dists/x.html", "pool.html", "dists.html", "Key.GPG", "INDEX.JSON"):
            with self.subTest(bad):
                shutil_rmtree(self.dist)
                self.basic(**{bad: b"evil"})
                store = storage.DirStorage(Path(self.tmp.name) / f"bucket-{abs(hash(bad))}")
                with self.assertRaises(site.SiteError):
                    site.upload(store, self.dist, log=lambda *_: None)
                self.assertEqual(store.headers, {}, "nothing is uploaded when any key is refused")

    def test_extensionless_copy_cannot_shadow_either(self):
        # A page named key.html would also be stored as "key.html" (allowed) but its copy "key" is fine;
        # index.json.html would create the extensionless copy "index.json", which must be refused.
        self.basic(**{"index.json.html": b"evil"})
        with self.assertRaises(site.SiteError):
            site.upload(self.store, self.dist, log=lambda *_: None)

    def test_refuses_a_build_made_from_sample_data(self):
        self.basic()
        (self.dist / "index.html").write_bytes(b'<head><meta name="site-data" content="sample"></head>')
        with self.assertRaises(site.SiteError):
            site.upload(self.store, self.dist, log=lambda *_: None)
        self.assertEqual(self.store.headers, {})

    def test_build_passes_the_exported_file_to_astro(self):
        calls = []
        def fake_run(cmd, cwd=None, env=None):
            calls.append((cmd, Path(cwd), env.get("SITE_DATA")))
            return mock.Mock(returncode=0)
        with mock.patch.object(site.subprocess, "run", fake_run):
            dist = site.build(Path(self.tmp.name) / "site", data=Path(self.tmp.name) / "d.json", log=lambda *_: None)
        self.assertEqual([c[0] for c in calls], [["npm", "ci"], ["npm", "run", "build"]])
        self.assertTrue(all(c[2] == str(Path(self.tmp.name).resolve() / "d.json") for c in calls))
        self.assertEqual(dist, Path(self.tmp.name) / "site" / "dist")
        with mock.patch.object(site.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(site.SiteError):
                site.build(Path(self.tmp.name), log=lambda *_: None)

    def test_requires_a_build_and_refuses_symlinks(self):
        with self.assertRaises(site.SiteError):
            site.upload(self.store, self.dist, log=lambda *_: None)
        self.basic()
        (self.dist / "link").symlink_to("/etc/passwd")
        with self.assertRaises(site.SiteError):
            site.upload(self.store, self.dist, log=lambda *_: None)


def shutil_rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class SiteCli(unittest.TestCase):
    def test_site_data_and_upload_site_commands(self):
        import contextlib
        from aptrepo import cli
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            tmp = Path(tmp)
            _, pub = make_key(tmp / "gnupg")
            (tmp / "pub.asc").write_bytes(pub)
            (tmp / "repo.toml").write_text(
                '[repository]\norigin="T"\narchitectures=["amd64"]\nbase_url="https://apt.example.test/"\n'
                f'key_file="{tmp / "pub.asc"}"\n')
            index = tmp / "index.json"
            index.write_text(json.dumps(repo.empty_state()))
            out = tmp / "data" / "site-data.json"
            with mock.patch.object(cli, "ROOT", tmp):
                code = cli.main(["site-data", "--config", str(tmp / "repo.toml"), "--index", str(index),
                                 "--storage", f"dir:{tmp / 'b'}", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text())["repo"]["baseUrl"], "https://apt.example.test")
            dist = tmp / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("home")
            (dist / "packages.html").write_text("pkgs")
            self.assertEqual(cli.main(["upload-site", str(dist), "--storage", f"dir:{tmp / 'b'}"]), 0)
            self.assertEqual((tmp / "b" / "packages").read_text(), "pkgs")
            (dist / "key.gpg").write_text("evil")
            self.assertEqual(cli.main(["upload-site", str(dist), "--storage", f"dir:{tmp / 'b'}"]), 1)
            self.assertFalse((tmp / "b" / "key.gpg").exists())


class SetupScript(unittest.TestCase):
    """site/public/setup.sh repeats a few repository facts; they must not drift."""

    ROOT = Path(__file__).resolve().parent.parent
    SCRIPT = (ROOT / "site" / "public" / "setup.sh").read_text()

    def value(self, name):
        found = re.search(rf'^{name}="(?:\$\{{[A-Z_]+:-)?([^"}}]*)\}}?"', self.SCRIPT, re.M)
        self.assertIsNotNone(found, f"{name} not found in setup.sh")
        return found.group(1)

    def config(self):
        import tomllib

        with (self.ROOT / "repo.toml").open("rb") as fh:
            return repo.RepoConfig.from_toml(tomllib.load(fh))

    def test_repository_facts_match_repo_toml(self):
        cfg = self.config()
        self.assertEqual(self.value("BASE_URL"), cfg.base_url)
        self.assertEqual(self.value("SUITE"), cfg.suite)
        self.assertEqual(self.value("COMPONENT"), cfg.component)

    def test_key_pins_match_the_committed_key(self):
        armored = (self.ROOT / "keys" / "rafaelvieiras-apt.asc").read_bytes()
        self.assertEqual(self.value("FINGERPRINT"), sign.public_fingerprint(armored))
        self.assertEqual(self.value("KEY_SHA256"), hashlib.sha256(sign.dearmor(armored)).hexdigest())

    def test_paths_match_the_site_and_the_docs(self):
        self.assertEqual(self.value("KEYRING"), "/etc/apt/keyrings/rafaelvieiras-apt.gpg")
        self.assertEqual(self.value("SOURCES"), "/etc/apt/sources.list.d/rafaelvieiras-apt.sources")
        lib = (self.ROOT / "site" / "src" / "lib" / "site.ts").read_text()
        self.assertIn(self.value("KEYRING"), lib)
        self.assertIn(self.value("SOURCES"), lib)

    def test_is_posix_sh_and_executable(self):
        self.assertTrue(self.SCRIPT.startswith("#!/bin/sh\n"))
        self.assertIn("set -eu", self.SCRIPT)
        self.assertNotIn("[[", self.SCRIPT)
        self.assertTrue((self.ROOT / "site" / "public" / "setup.sh").stat().st_mode & 0o111)

    def test_runs_nothing_before_the_last_line(self):
        last = [line for line in self.SCRIPT.splitlines() if line.strip()][-1]
        self.assertEqual(last, 'main "$@"')
        self.assertEqual(self.SCRIPT.count('main "$@"'), 1)

    def test_is_served_as_text_with_a_short_cache(self):
        self.assertEqual(storage.content_type("setup.sh"), "text/plain; charset=utf-8")
        self.assertEqual(storage.cache_control("setup.sh"), storage.SHORT)

    def test_upload_plan_includes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_bytes(b"<h1>home")
            (dist / "setup.sh").write_bytes(b"#!/bin/sh\n")
            self.assertIn("setup.sh", [key for key, _, _ in site.plan_upload(dist)])

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "TMPDIR": tmp, "NO_COLOR": "1"}
            done = subprocess.run(["sh", str(self.ROOT / "site" / "public" / "setup.sh"), "--dry-run"],
                                  capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("nothing was installed", done.stderr)
            self.assertEqual(list(Path(tmp).iterdir()), [], "dry run must leave no temporary files behind")

    def test_never_installs_packages(self):
        self.assertNotIn("apt-get install", self.SCRIPT)
        self.assertNotIn("apt install -y", self.SCRIPT)
        for args in (["neovim"], ["--", "neovim"], ["--dry-run", "a;rm -rf /"]):
            done = subprocess.run(["sh", str(self.ROOT / "site" / "public" / "setup.sh"), *args],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 2, args)
            self.assertIn("unknown argument", done.stderr)


class SetMetadata(unittest.TestCase):
    def state(self):
        state = repo.load_state(None)
        repo.add_version(state, name="t", homepage="h", license="MIT", version="1-1", upstream_version="1",
                         source="s", released="r", arches={"amd64": {"control": "Description: d", "filename": "f"}},
                         note="n")
        return state

    def test_reports_whether_anything_changed(self):
        state = self.state()
        self.assertFalse(repo.set_metadata(state, "t", homepage="h", license="MIT", note="n"))
        self.assertTrue(repo.set_metadata(state, "t", homepage="h2", license="MIT", note="n"))
        self.assertTrue(repo.set_metadata(state, "t", homepage="h2", license="GPL", note="n"))
        self.assertTrue(repo.set_metadata(state, "t", homepage="h2", license="GPL", note=""))
        self.assertNotIn("note", state["packages"]["t"])
        self.assertFalse(repo.set_metadata(state, "t", homepage="h2", license="GPL", note=""))


class RecipeNote(unittest.TestCase):
    def test_note_is_parsed_stored_and_optional(self):
        base = {"name": "tool", "license": "MIT", "source": {"repo": "a/b"}, "build": {"kind": "deb"},
                "assets": {"amd64": "t.deb"}}
        self.assertEqual(recipe.parse_recipe(base).note, "")
        self.assertEqual(recipe.parse_recipe({**base, "note": " Needs X. "}).note, "Needs X.")
        state = repo.empty_state()
        kw = dict(name="tool", homepage="h", license="MIT", version="1-1", upstream_version="1", source="s",
                  released="r", arches={"amd64": {"control": "Description: d"}})
        repo.add_version(state, note="Needs X.", **kw)
        self.assertEqual(state["packages"]["tool"]["note"], "Needs X.")
        repo.set_note(state, "tool", "")
        self.assertNotIn("note", state["packages"]["tool"])

    def test_every_shipped_recipe_note_is_short(self):
        for r in recipe.load_recipes(ROOT / "packages"):
            self.assertLess(len(r.note), 120, r.name)


class PublishFlow(unittest.TestCase):
    """Full publish against a fake upstream and a directory bucket."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.sec, self.pub = make_key(self.dir / "gnupg")
        self.key_path = self.dir / "pub.asc"
        self.key_path.write_bytes(self.pub)
        (self.dir / "packages").mkdir()
        (self.dir / "packages" / "tool.toml").write_text(
            'name="tool"\nlicense="MIT"\nnote="Needs nothing."\n[source]\nrepo="a/b"\n[build]\nkind="tarball"\nlicense_path="L"\n'
            '[assets]\namd64="t.tgz"\n[package]\nsection="utils"\ndescription="Short\\nLong"\n'
            '[[companion]]\nname="tool-runtime"\ndescription="Transitional\\nEmpty"\n'
        )
        self.tgz = self.dir / "t.tgz"
        make_tarball(self.tgz)
        self.tag = "v1.0.0"
        self.store = storage.DirStorage(self.dir / "bucket")

    def _copy_tgz(self, asset, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.tgz.read_bytes())
        return "x"

    def run_publish(self, **kw):
        def fake_latest(_repo):
            asset = upstream.Asset("t.tgz", "https://example.invalid/t.tgz", 1, None)
            return upstream.Release(self.tag, "2026-01-01T00:00:00Z", {"t.tgz": asset})

        def fake_download(asset, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.tgz.read_bytes())
            return "x"

        with mock.patch.object(upstream, "latest_release", fake_latest), \
             mock.patch.object(upstream, "download", fake_download), \
             mock.patch.object(upstream, "fetch_text", lambda url: "MIT text"):
            return publish.publish(CFG, self.dir / "packages", self.store, private_key=self.sec,
                                   passphrase=None, log=lambda *_: None, key_path=self.key_path, **kw)

    def test_publish_signs_uploads_and_is_idempotent(self):
        first = self.run_publish()
        self.assertEqual((first.published, first.errors), (["tool"], []))
        sign.verify_clearsigned(self.pub, self.store.get("dists/stable/InRelease"))
        state = json.loads(self.store.get("index.json"))
        self.assertEqual(set(state["packages"]), {"tool", "tool-runtime"})
        self.assertEqual(state["packages"]["tool"]["note"], "Needs nothing.")
        self.assertNotIn("note", state["packages"]["tool-runtime"])
        self.assertFalse(self.store.exists("index.html"), "the site is published by its own step")
        self.assertTrue(self.store.exists("pool/main/t/tool/tool_1.0.0-1_amd64.deb"))
        self.assertTrue(self.store.exists("pool/main/t/tool-runtime/tool-runtime_1.0.0-1_amd64.deb"))
        self.assertEqual(self.store.headers["pool/main/t/tool/tool_1.0.0-1_amd64.deb"], storage.IMMUTABLE)
        self.assertEqual(self.store.headers["dists/stable/InRelease"], storage.SHORT)
        before = self.store.get("dists/stable/InRelease")
        second = self.run_publish()
        self.assertEqual((second.published, second.skipped), ([], ["tool"]))
        self.assertEqual(self.store.get("dists/stable/InRelease"), before, "no-op must not re-sign")

    def edit_recipe(self, old, new):
        path = self.dir / "packages" / "tool.toml"
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1))

    def test_a_changed_note_is_published_without_forcing(self):
        self.run_publish()
        generated = json.loads(self.store.get("index.json"))["generated"]
        self.edit_recipe('note="Needs nothing."', 'note="Needs less than nothing."')
        again = self.run_publish(now=4_000_000_000)
        self.assertEqual((again.published, again.refreshed), ([], ["tool"]))
        state = json.loads(self.store.get("index.json"))
        self.assertEqual(state["packages"]["tool"]["note"], "Needs less than nothing.")
        self.assertNotEqual(state["generated"], generated, "index.json is rewritten, so the site sees the change")
        # A note is not in the .deb, so the apt indexes are identical; they are still valid and signed.
        sign.verify_clearsigned(self.pub, self.store.get("dists/stable/InRelease"))
        third = self.run_publish()
        self.assertEqual((third.refreshed, third.published), ([], []), "the second run has nothing left to refresh")

    def test_removing_a_note_is_published_too(self):
        self.run_publish()
        self.edit_recipe('note="Needs nothing."\n', "")
        again = self.run_publish()
        self.assertEqual(again.refreshed, ["tool"])
        self.assertNotIn("note", json.loads(self.store.get("index.json"))["packages"]["tool"])

    def test_a_changed_homepage_or_licence_is_published(self):
        self.run_publish()
        self.edit_recipe('license="MIT"', 'license="MIT"\nhomepage="https://example.invalid/tool"')
        self.assertEqual(self.run_publish().refreshed, ["tool"])
        self.assertEqual(json.loads(self.store.get("index.json"))["packages"]["tool"]["homepage"], "https://example.invalid/tool")

    def test_an_unchanged_recipe_refreshes_nothing(self):
        self.run_publish()
        before = self.store.get("dists/stable/InRelease")
        again = self.run_publish()
        self.assertEqual((again.published, again.refreshed), ([], []))
        self.assertEqual(self.store.get("dists/stable/InRelease"), before)

    def test_state_published_before_notes_existed_gets_them(self):
        self.run_publish()
        state = json.loads(self.store.get("index.json"))
        state["packages"]["tool"].pop("note")
        self.store.put("index.json", json.dumps(state).encode())
        self.assertEqual(self.run_publish().refreshed, ["tool"])
        self.assertEqual(json.loads(self.store.get("index.json"))["packages"]["tool"]["note"], "Needs nothing.")

    def test_a_dry_run_never_refreshes(self):
        self.run_publish()
        self.edit_recipe('note="Needs nothing."', 'note="Changed."')
        before = self.store.get("index.json")
        result = self.run_publish(dry_run=True)
        self.assertEqual(result.refreshed, [])
        self.assertEqual(self.store.get("index.json"), before)

    def test_a_recipe_for_an_unpublished_package_is_not_a_refresh(self):
        self.run_publish()
        (self.dir / "packages" / "new.toml").write_text(
            'name="new"\nlicense="MIT"\nnote="n"\n[source]\nrepo="a/n"\n[build]\nkind="tarball"\nlicense_path="L"\n'
            '[assets]\namd64="n.tgz"\n[package]\nsection="utils"\ndescription="S\\nL"\n')
        result = self.run_publish(only={"tool"})
        self.assertEqual(result.refreshed, [])

    def test_never_goes_backwards(self):
        self.run_publish()
        self.tag = "v0.9.0"
        again = self.run_publish()
        self.assertEqual(again.published, [])

    def test_new_release_prunes_and_cleans_pool(self):
        for tag in ("v1.0.0", "v1.1.0", "v1.2.0", "v1.3.0"):
            self.tag = tag
            self.run_publish()
        state = json.loads(self.store.get("index.json"))
        self.assertEqual(len(state["packages"]["tool"]["versions"]), CFG.retain)
        self.assertFalse(self.store.exists("pool/main/t/tool/tool_1.0.0-1_amd64.deb"))
        self.assertTrue(self.store.exists("pool/main/t/tool/tool_1.3.0-1_amd64.deb"))

    def test_refuses_unsigned_and_mismatched_key(self):
        with self.assertRaises(sign.SignError):
            with mock.patch.object(upstream, "latest_release", return_value=upstream.Release(
                    "v1.0.0", "", {"t.tgz": upstream.Asset("t.tgz", "u", 1, None)})), \
                 mock.patch.object(upstream, "download", self._copy_tgz), \
                 mock.patch.object(upstream, "fetch_text", lambda u: "L"):
                publish.publish(CFG, self.dir / "packages", self.store, private_key=None, passphrase=None,
                                log=lambda *_: None, key_path=self.key_path)
        other_home = self.dir / "other"
        other_home.mkdir()
        other_sec, _ = make_key(other_home)
        self.sec = other_sec
        with self.assertRaises(sign.SignError):
            self.run_publish()
        self.assertIsNone(self.store.get("dists/stable/InRelease"))

    def test_one_failing_package_does_not_block_others(self):
        (self.dir / "packages" / "bad.toml").write_text(
            'name="bad"\nlicense="Proprietary"\n[source]\nrepo="a/c"\n[build]\nkind="deb"\n[assets]\namd64="b.deb"\n')
        result = self.run_publish()
        self.assertEqual(result.published, ["tool"])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("allowlist", result.errors[0])


if __name__ == "__main__":
    unittest.main()
