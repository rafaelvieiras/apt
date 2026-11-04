"""Static landing page. One HTML file, no JavaScript, no external requests."""

from __future__ import annotations

from html import escape

from . import repo

CSS = """
:root{color-scheme:light dark;--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1da;--acc:#b4521c;--code:#f0efe8}
@media(prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe4;--mut:#9a9a92;--line:#2b2b27;--acc:#e08a52;--code:#1f1f1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
main{max-width:46rem;margin:0 auto;padding:3rem 1.25rem 4rem}
h1{font-size:1.9rem;margin:0 0 .25rem}h2{font-size:1.1rem;margin:2.5rem 0 .75rem}
p{margin:.5rem 0}.mut{color:var(--mut)}a{color:var(--acc)}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:.9rem 1rem;overflow-x:auto;font-size:.85rem;line-height:1.5}
code{font-family:ui-monospace,monospace;font-size:.9em}
table{width:100%;border-collapse:collapse;font-size:.92rem}th,td{text-align:left;padding:.5rem .4rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
footer{margin-top:3rem;color:var(--mut);font-size:.85rem}
"""


def render(state: dict, cfg: repo.RepoConfig, fingerprint: str) -> str:
    rows = []
    for name in sorted(state["packages"]):
        entry = state["packages"][name]
        newest = repo.newest_version(entry)
        if newest is None:
            continue
        info = entry["versions"][newest]
        arches = ", ".join(sorted(info["arch"]))
        rows.append(
            "<tr>"
            f"<td><a href=\"{escape(entry['homepage'])}\"><code>{escape(name)}</code></a></td>"
            f"<td><code>{escape(newest)}</code></td>"
            f"<td>{escape(arches)}</td>"
            f"<td>{escape(entry.get('description', ''))}</td>"
            "</tr>"
        )
    table = "\n".join(rows) or '<tr><td colspan="4" class="mut">No packages yet.</td></tr>'
    base = escape(cfg.base_url)
    pretty = " ".join(fingerprint[i : i + 4] for i in range(0, len(fingerprint), 4))
    sources = (
        "Types: deb\n"
        f"URIs: {base}/\n"
        f"Suites: {cfg.suite}\n"
        f"Components: {cfg.component}\n"
        "Signed-By: /etc/apt/keyrings/rafaelvieiras-apt.gpg\n"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(cfg.origin)}</title>
<meta name="description" content="{escape(cfg.description)}">
<style>{CSS}</style></head><body><main>
<h1>{escape(cfg.origin)}</h1>
<p class="mut">{escape(cfg.description)}</p>

<h2>Add the repository</h2>
<pre>sudo install -d -m 0755 /etc/apt/keyrings
sudo curl -fsSL {base}/key.gpg -o /etc/apt/keyrings/rafaelvieiras-apt.gpg
sudo tee /etc/apt/sources.list.d/rafaelvieiras-apt.sources &gt;/dev/null &lt;&lt;'EOF'
{escape(sources)}EOF
sudo apt update</pre>
<p class="mut">Works on any Debian or Ubuntu release. Packages are static binaries, so
there is one suite for all of them.</p>

<h2>Packages</h2>
<table><thead><tr><th>Package</th><th>Version</th><th>Arch</th><th>Description</th></tr></thead>
<tbody>
{table}
</tbody></table>
<p class="mut">The same list as JSON: <a href="index.json"><code>index.json</code></a>.</p>

<h2>Verify the key</h2>
<pre>gpg --show-keys /etc/apt/keyrings/rafaelvieiras-apt.gpg
# fingerprint must be {escape(pretty)}</pre>

<footer>Built from public upstream releases by
<a href="https://github.com/rafaelvieiras/apt">rafaelvieiras/apt</a>.
Generated {escape(state.get("generated", ""))}.</footer>
</main></body></html>
"""
