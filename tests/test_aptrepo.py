"""Offline tests. Upstream is faked, GnuPG and dpkg-deb are real."""

from __future__ import annotations

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


class Site(unittest.TestCase):
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
                version="1.2.3-1", upstream_version="1.2.3", source="https://x/r", released="2026-05-19T10:00:00Z",
                arches={a: {"filename": "f", "size": 1, "md5": "", "sha1": "", "sha256": "",
                            "control": f"Package: {name}\nDescription: {kw.get('desc', 'Does things')}"}
                        for a in ("amd64", "arm64")},
                note=kw.get("note", ""),
            )
        return s

    def page(self, state=None):
        return site.render(state or self.state(), CFG, self.FP)

    def test_install_snippet_uses_config_and_fixed_paths(self):
        page = self.page()
        for text in (
            f"sudo curl -fsSL {CFG.base_url}/key.gpg -o /etc/apt/keyrings/rafaelvieiras-apt.gpg",
            "sudo tee /etc/apt/sources.list.d/rafaelvieiras-apt.sources",
            "Types: deb", f"URIs: {CFG.base_url}/", f"Suites: {CFG.suite}", f"Components: {CFG.component}",
            "Signed-By: /etc/apt/keyrings/rafaelvieiras-apt.gpg", "sudo apt update",
        ):
            self.assertIn(text, page)

    def test_fingerprint_and_packages_are_listed(self):
        page = self.page()
        self.assertIn("A1B2 C3D4 E5F6 0718 293A", page)
        self.assertIn(f'data-copy="{self.FP}"', page)
        for name in ("alpha", "beta"):
            self.assertIn(f"sudo apt install {name}", page)
        self.assertIn("1.2.3", page)
        self.assertIn("Needs glibc 2.38 or newer.", page)
        self.assertIn("2026-05-20 06:17 UTC", page)
        self.assertNotIn("sudo apt install beta-runtime", page)  # transitional: listed, not a card
        self.assertIn("beta-runtime", page)

    def test_old_state_without_notes_renders(self):
        state = self.state()
        for entry in state["packages"].values():
            entry.pop("note", None)
        self.assertIn("sudo apt install alpha", self.page(state))
        self.assertIn("No packages published yet", self.page(repo.empty_state()))

    def test_hostile_values_are_escaped(self):
        evil = '"><script>alert(1)</script>'
        state = self.state(alpha={"homepage": "javascript:alert(1)", "note": evil, "desc": evil})
        cfg = repo.RepoConfig(**{**CFG.__dict__, "origin": evil, "description": evil})
        page = site.render(state, cfg, "AB" + evil)
        self.assertNotIn(evil, page)
        self.assertEqual(page.count("<script>"), 1)  # only the copy-button script
        self.assertNotIn("javascript:", page)

    def test_no_external_resources_and_small(self):
        page = self.page()
        self.assertFalse(re.search(r'<(?:script|img|iframe|source|audio|video)\b[^>]*\bsrc=', page))
        self.assertFalse(re.search(r'<link\b[^>]*rel="(?:stylesheet|preload|prefetch|preconnect)"', page))
        self.assertNotIn("@import", page)
        self.assertNotRegex(page, r"url\(\s*['\"]?(?:https?:)?//")
        self.assertLess(len(page.encode()), 60_000)

    def test_page_works_without_javascript(self):
        page = self.page()
        self.assertIn('lang="en"', page)
        self.assertIn('class="skip"', page)
        self.assertRegex(page, r'<button type="button" class="copy"[^>]* hidden')  # hidden until JS enables it
        self.assertIn("<details>", page)


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
        self.assertIn(b"Needs nothing.", self.store.get("index.html"))
        self.assertTrue(self.store.exists("pool/main/t/tool/tool_1.0.0-1_amd64.deb"))
        self.assertTrue(self.store.exists("pool/main/t/tool-runtime/tool-runtime_1.0.0-1_amd64.deb"))
        self.assertEqual(self.store.headers["pool/main/t/tool/tool_1.0.0-1_amd64.deb"], storage.IMMUTABLE)
        self.assertEqual(self.store.headers["dists/stable/InRelease"], storage.SHORT)
        before = self.store.get("dists/stable/InRelease")
        second = self.run_publish()
        self.assertEqual((second.published, second.skipped), ([], ["tool"]))
        self.assertEqual(self.store.get("dists/stable/InRelease"), before, "no-op must not re-sign")

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
