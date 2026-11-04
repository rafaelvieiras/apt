"""Static landing page.

One self-contained HTML file: inline CSS and SVG, no external requests. The only
script is a few lines of progressive enhancement (copy buttons); everything is
readable and usable without it.
"""

from __future__ import annotations

import re
from html import escape

from . import repo

SOURCE_URL = "https://github.com/rafaelvieiras/apt"
CHECK_HOURS = 6  # keep in sync with the cron in .github/workflows/publish.yml
KEYRING = "/etc/apt/keyrings/rafaelvieiras-apt.gpg"
SOURCES = "/etc/apt/sources.list.d/rafaelvieiras-apt.sources"

FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='8' fill='%230f766e'/%3E"
    "%3Cpath d='M9 11l6 5-6 5M17 22h7' fill='none' stroke='white' stroke-width='2.6' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"
)

CSS = """
:root{color-scheme:light dark;--bg:#fbfbfa;--bg2:#f2f4f3;--card:#fff;--fg:#14201f;--mut:#52605f;--line:#dfe4e2;
--acc:#0f766e;--acc-fg:#fff;--acc-soft:#e0f2ef;--glow:rgba(15,118,110,.16);--glow2:rgba(99,102,241,.10);
--term:#0d1618;--term-fg:#e4eceb;--term-mut:#8ea3a1;--term-line:#22343a;--shadow:0 1px 2px rgba(20,32,31,.05),0 8px 24px -12px rgba(20,32,31,.18)}
@media(prefers-color-scheme:dark){:root{--bg:#0a1112;--bg2:#0f1819;--card:#121d1e;--fg:#e6eeed;--mut:#9aaaa8;--line:#223133;
--acc:#5eead4;--acc-fg:#032420;--acc-soft:#133533;--glow:rgba(94,234,212,.10);--glow2:rgba(129,140,248,.10);
--term:#070d0e;--term-line:#1f2e31;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -12px rgba(0,0,0,.6)}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:1rem}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
a{color:var(--acc);text-underline-offset:.2em}a:hover{text-decoration-thickness:2px}
:focus-visible{outline:3px solid var(--acc);outline-offset:3px;border-radius:4px}
code,pre{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace}
h1,h2,h3{line-height:1.15;margin:0;letter-spacing:-.02em}p{margin:0}
.wrap{max-width:72rem;margin:0 auto;padding:0 1.25rem}
.skip{position:absolute;left:-999px;top:.5rem;background:var(--acc);color:var(--acc-fg);padding:.5rem .9rem;border-radius:6px;z-index:10}
.skip:focus{left:.5rem}
.mut{color:var(--mut)}
header.top{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:1rem 0}
.brand{display:flex;align-items:center;gap:.6rem;font-weight:700;color:var(--fg);text-decoration:none;letter-spacing:-.01em}
.brand svg{width:1.7rem;height:1.7rem;flex:none}
nav ul{display:flex;gap:.25rem;list-style:none;margin:0;padding:0;align-items:center}
nav a{display:block;padding:.4rem .7rem;border-radius:999px;color:var(--mut);text-decoration:none;font-size:.92rem}
nav a:hover{color:var(--fg);background:var(--bg2)}
nav .gh{border:1px solid var(--line);color:var(--fg)}
.hero{position:relative;overflow:hidden;border-bottom:1px solid var(--line);
background:radial-gradient(60rem 28rem at 85% -10%,var(--glow),transparent 70%),radial-gradient(40rem 24rem at -10% 20%,var(--glow2),transparent 70%),var(--bg)}
.hero:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.5;
background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:44px 44px;
-webkit-mask-image:radial-gradient(70% 60% at 70% 30%,#000,transparent);mask-image:radial-gradient(70% 60% at 70% 30%,#000,transparent)}
.hero .wrap{position:relative}
.hero-grid{display:grid;gap:2.5rem;padding:2.5rem 0 4rem;align-items:center}
@media(min-width:62rem){.hero-grid{grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);padding:4rem 0 5.5rem;gap:3.5rem}}
.pill{display:inline-flex;align-items:center;gap:.5rem;padding:.25rem .75rem;border:1px solid var(--line);border-radius:999px;background:var(--card);font-size:.82rem;color:var(--mut)}
.pill i{width:.5rem;height:.5rem;border-radius:50%;background:var(--acc);box-shadow:0 0 0 3px var(--acc-soft)}
h1{font-size:clamp(2.25rem,6vw,3.6rem);margin:1.1rem 0 1rem;font-weight:800}
h1 em{font-style:normal;color:var(--acc)}
.lead{font-size:1.15rem;color:var(--mut);max-width:34rem}
.cta{display:flex;flex-wrap:wrap;gap:.75rem;margin:1.75rem 0 2rem}
.btn{display:inline-flex;align-items:center;gap:.5rem;padding:.7rem 1.2rem;border-radius:10px;font-weight:600;text-decoration:none;border:1px solid var(--line);color:var(--fg);background:var(--card);transition:transform .15s,box-shadow .15s}
.btn:hover{transform:translateY(-1px);box-shadow:var(--shadow)}
.btn.primary{background:var(--acc);color:var(--acc-fg);border-color:var(--acc)}
.stats{display:flex;flex-wrap:wrap;gap:1.5rem 2.5rem;margin:0;padding:0;list-style:none}
.stats b{display:block;font-size:1.7rem;line-height:1.1;letter-spacing:-.02em}
.stats span{font-size:.85rem;color:var(--mut)}
section{padding:4.5rem 0}section.alt{background:var(--bg2);border-block:1px solid var(--line)}
.eyebrow{font-size:.8rem;text-transform:uppercase;letter-spacing:.12em;color:var(--acc);font-weight:700;margin-bottom:.6rem}
h2{font-size:clamp(1.65rem,4vw,2.3rem);font-weight:800}
.sub{color:var(--mut);max-width:40rem;margin-top:.8rem;font-size:1.05rem}
.head{margin-bottom:2.25rem}
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(min(100%,19rem),1fr))}
.why{grid-template-columns:repeat(auto-fill,minmax(min(100%,13rem),1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.4rem;transition:border-color .15s,box-shadow .15s,transform .15s}
.card:hover,.card:focus-within{border-color:var(--acc);box-shadow:var(--shadow);transform:translateY(-2px)}
.card h3{font-size:1.05rem;margin:.9rem 0 .4rem;letter-spacing:-.01em}.card p{color:var(--mut);font-size:.95rem}
.ico{width:2.6rem;height:2.6rem;border-radius:11px;background:var(--acc-soft);color:var(--acc);display:grid;place-items:center}
.ico svg{width:1.4rem;height:1.4rem;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.term{margin:0;border:1px solid var(--term-line);border-radius:12px;background:var(--term);color:var(--term-fg);overflow:hidden;box-shadow:var(--shadow);min-width:0}
.term figcaption{display:flex;align-items:center;gap:.4rem;padding:.55rem .8rem;border-bottom:1px solid var(--term-line);font-size:.78rem;color:var(--term-mut)}
.term figcaption i{width:.65rem;height:.65rem;border-radius:50%;background:#2c3e43}
.term figcaption span{margin-left:.4rem;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.term pre{margin:0;padding:1rem 1.1rem;overflow-x:auto;font-size:.82rem;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}
.term pre code,.steps .term code,details .term code{background:none;border:0;padding:0;font-size:inherit;color:inherit}
.term .c{color:var(--term-mut)}.term .p{color:#5eead4;user-select:none}
.copy{font:inherit;font-size:.78rem;cursor:pointer;color:var(--term-fg);background:transparent;border:1px solid var(--term-line);border-radius:7px;padding:.2rem .65rem}
.copy:hover{background:#1a2a2e}.copy:focus-visible{outline-color:#5eead4}
.copy[hidden]{display:none}
.cmd{display:flex;align-items:center;gap:.5rem;margin-top:auto;background:var(--term);color:var(--term-fg);border-radius:9px;padding:.35rem .4rem .35rem .8rem;min-width:0}
.cmd code{flex:1;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem;padding:.3rem 0}
.steps{list-style:none;margin:0;padding:0;display:grid;gap:2rem;counter-reset:s}
.steps>li{display:grid;gap:1rem;grid-template-columns:minmax(0,1fr);counter-increment:s}
@media(min-width:62rem){.steps>li{grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:2.5rem;align-items:start}}
.steps h3{font-size:1.2rem;display:flex;gap:.8rem;align-items:center}
.steps h3:before{content:counter(s);flex:none;width:2rem;height:2rem;border-radius:50%;background:var(--acc);color:var(--acc-fg);display:grid;place-items:center;font-size:.95rem}
.steps p{margin-top:.6rem;color:var(--mut)}.steps dl{margin:.8rem 0 0;font-size:.9rem;color:var(--mut)}
.steps dt{display:inline;font-family:ui-monospace,monospace;color:var(--fg);font-size:.85rem}.steps dd{display:inline;margin:0}.steps dd:after{content:"";display:block;margin-bottom:.35rem}
.steps code{background:var(--bg2);border:1px solid var(--line);border-radius:5px;padding:0 .3rem;font-size:.85em}
.pkg{display:flex;flex-direction:column;gap:.9rem}
.pkg-head{display:flex;gap:.9rem;align-items:center}
.mono{flex:none;width:2.8rem;height:2.8rem;border-radius:12px;display:grid;place-items:center;font-weight:800;font-size:1.25rem;
background:hsl(var(--h) 55% 91%);color:hsl(var(--h) 60% 27%)}
@media(prefers-color-scheme:dark){.mono{background:hsl(var(--h) 35% 20%);color:hsl(var(--h) 75% 78%)}}
.pkg h3{margin:0;font-size:1.15rem}.pkg h3 a{color:var(--fg);text-decoration:none}.pkg h3 a:hover{color:var(--acc)}
.ver{font-size:.82rem;color:var(--mut)}.ver b{color:var(--fg);font-family:ui-monospace,monospace}
.pkg p{color:var(--mut);font-size:.95rem;margin:0}
.tags{display:flex;flex-wrap:wrap;gap:.4rem;list-style:none;margin:0;padding:0}
.tags li{font-size:.75rem;padding:.12rem .55rem;border-radius:999px;border:1px solid var(--line);background:var(--bg2);color:var(--mut)}
.tags li.arch{font-family:ui-monospace,monospace}
.note{font-size:.85rem;color:var(--fg);background:var(--acc-soft);border-radius:9px;padding:.5rem .7rem}
.up{font-size:.85rem}
.trans{margin-top:1.5rem;font-size:.9rem;color:var(--mut)}
.two{display:grid;gap:2rem}@media(min-width:62rem){.two{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:3rem;align-items:start}}
.flow{list-style:none;margin:0;padding:0;display:grid;gap:.75rem}
.flow li{display:grid;grid-template-columns:2.4rem 1fr;gap:.9rem;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:.9rem 1rem}
.flow b{display:block}.flow span{color:var(--mut);font-size:.92rem}
.flow .n{width:2.4rem;height:2.4rem;border-radius:50%;background:var(--acc-soft);color:var(--acc);display:grid;place-items:center;font-weight:700}
.fp{font-family:ui-monospace,monospace;font-size:1.02rem;letter-spacing:.02em;word-spacing:.35em;padding:1rem 1.1rem;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:10px;margin:1rem 0;overflow-wrap:anywhere}
.fp-row{display:flex;gap:.6rem;align-items:flex-start}.fp-row .fp{flex:1;margin:1rem 0}
.copy.light{color:var(--fg);border-color:var(--line);margin-top:1rem}.copy.light:hover{background:var(--bg2)}
.links{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;list-style:none;margin:1.25rem 0 0;padding:0}
.os{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(min(100%,13rem),1fr))}
.os h3{font-size:1rem}.os ul{margin:.6rem 0 0;padding-left:1.1rem;color:var(--mut);font-size:.93rem}
.faq{display:grid;gap:.75rem;max-width:50rem}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:0 1.2rem}
details[open]{border-color:var(--acc)}
summary{cursor:pointer;font-weight:600;padding:1rem 0;list-style:none;display:flex;justify-content:space-between;gap:1rem;border-radius:8px}
summary::-webkit-details-marker{display:none}
summary:after{content:"+";color:var(--acc);font-size:1.3rem;line-height:1}details[open] summary:after{content:"\\2212"}
details>div{padding:0 0 1.1rem;color:var(--mut)}details>div>*+*{margin-top:.8rem}
details code{color:var(--fg);background:var(--bg2);border:1px solid var(--line);border-radius:5px;padding:0 .3rem;font-size:.85em}
footer{border-top:1px solid var(--line);padding:2.5rem 0 3rem;color:var(--mut);font-size:.9rem}
footer .wrap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:1rem 2rem}
footer ul{display:flex;flex-wrap:wrap;gap:.4rem 1.25rem;list-style:none;margin:0;padding:0}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media(max-width:40rem){nav li:not(:last-child){display:none}section{padding:3.25rem 0}.hero-grid{padding-bottom:3rem}}
"""

JS = """
(function(){
var live=document.getElementById("live");
function copy(text){
  if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(text);
  return new Promise(function(ok,no){
    var t=document.createElement("textarea");t.value=text;t.setAttribute("readonly","");
    t.style.position="fixed";t.style.opacity="0";document.body.appendChild(t);t.select();
    try{document.execCommand("copy")?ok():no()}catch(e){no()}document.body.removeChild(t);
  });
}
document.querySelectorAll(".copy").forEach(function(b){
  b.hidden=false;
  b.addEventListener("click",function(){
    var src=b.getAttribute("data-copy");
    if(src===null){var c=b.closest("[data-root]").querySelector("code");src=c.textContent.replace(/\\n$/,"")}
    var label=b.textContent;
    copy(src).then(function(){b.textContent="Copied";live.textContent="Copied to clipboard"},
                   function(){b.textContent="Press Ctrl+C";live.textContent="Copy failed"});
    setTimeout(function(){b.textContent=label;live.textContent=""},1800);
  });
});
})();
"""

_ICONS = {
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "layers": '<path d="M12 3 3 8l9 5 9-5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5"/>',
    "shield": '<path d="M12 21s8-3.5 8-10V5.5L12 3 4 5.5V11c0 6.5 8 10 8 10z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "nobody": '<circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/>',
    "code": '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5V8zM3 8l9 5 9-5M12 13v8"/>',
}


def _icon(name: str) -> str:
    return f'<span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{_ICONS[name]}</svg></span>'


def _safe_url(url: str) -> str:
    """Only http(s) links are rendered as links; anything else becomes '#'."""
    return url if re.match(r"https?://", url or "") else "#"


def _copy_button(label: str, *, text: str | None = None, light: bool = False) -> str:
    data = f' data-copy="{escape(text)}"' if text is not None else ""
    cls = "copy light" if light else "copy"
    return f'<button type="button" class="{cls}" hidden{data} aria-label="{escape(label)}">Copy</button>'


def _terminal(title: str, body: str, label: str) -> str:
    """Terminal-style block. ``body`` is trusted HTML; ``label`` names the copy button."""
    return (
        '<figure class="term" data-root><figcaption><i></i><i></i><i></i>'
        f"<span>{escape(title)}</span>{_copy_button(label)}</figcaption>"
        f'<pre tabindex="0"><code>{body}</code></pre></figure>'
    )


def _cmd(command: str, label: str) -> str:
    return f'<div class="cmd" data-root><code>{escape(command)}</code>{_copy_button(label)}</div>'


def _lines(*parts: str) -> str:
    return "\n".join(parts)


def _comment(text: str) -> str:
    return f'<span class="c"># {escape(text)}</span>'


def _day(stamp: str) -> str:
    match = re.match(r"\d{4}-\d{2}-\d{2}", stamp or "")
    return match.group(0) if match else ""


def _is_transitional(entry: dict) -> bool:
    # Debian convention: empty compatibility packages say so in their synopsis.
    return entry.get("description", "").lower().startswith("transitional")


def _package_card(name: str, entry: dict) -> str:
    newest = repo.newest_version(entry)
    info = entry["versions"][newest]
    version = info.get("upstream_version") or newest
    released = _day(info.get("released", ""))
    arches = sorted(info["arch"])
    tags = [f'<li class="arch">{escape(a)}</li>' for a in arches]
    if entry.get("license"):
        tags.append(f"<li>{escape(entry['license'])}</li>")
    note = f'<p class="note">{escape(entry["note"])}</p>' if entry.get("note") else ""
    when = f"<br>released {escape(released)}" if released else ""
    return (
        '<article class="card pkg">'
        '<div class="pkg-head">'
        f'<span class="mono" style="--h:{sum(map(ord, name)) * 7 % 360}" aria-hidden="true">{escape(name[:1].upper())}</span>'
        f'<div><h3><a href="{escape(_safe_url(entry.get("homepage", "")))}">{escape(name)}</a></h3>'
        f'<div class="ver">v<b>{escape(version)}</b>{when}</div></div></div>'
        f'<p>{escape(entry.get("description", ""))}</p>'
        f'<ul class="tags" aria-label="Architectures and licence">{"".join(tags)}</ul>'
        f"{note}"
        f'<a class="up" href="{escape(_safe_url(entry.get("homepage", "")))}">Upstream project &#8599;</a>'
        f'{_cmd(f"sudo apt install {name}", f"Copy install command for {name}")}'
        "</article>"
    )


def _catalogue(state: dict) -> tuple[str, str, int]:
    cards, transitional = [], []
    for name in sorted(state["packages"]):
        entry = state["packages"][name]
        if repo.newest_version(entry) is None:
            continue
        if _is_transitional(entry):
            transitional.append(f"<code>{escape(name)}</code> ({escape(entry.get('description', '').lower())})")
        else:
            cards.append(_package_card(name, entry))
    grid = (
        f'<div class="grid">{"".join(cards)}</div>'
        if cards
        else '<p class="mut">No packages published yet.</p>'
    )
    trans = (
        f'<p class="trans">Also published: {"; ".join(transitional)}. They exist only so upgrades keep working.</p>'
        if transitional
        else ""
    )
    return grid, trans, len(cards)


def _pretty_fingerprint(fingerprint: str) -> str:
    groups = [fingerprint[i : i + 4] for i in range(0, len(fingerprint), 4)]
    return "  ".join(" ".join(groups[i : i + 5]) for i in range(0, len(groups), 5))


def _stamp(generated: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", generated or "")
    return f"{match.group(1)} {match.group(2)} UTC" if match else generated or "unknown"


def render(state: dict, cfg: repo.RepoConfig, fingerprint: str) -> str:
    base = cfg.base_url
    e = escape
    grid, transitional, count = _catalogue(state)
    names = [n for n in sorted(state["packages"]) if not _is_transitional(state["packages"][n])]
    sample = " ".join(names[:3]) or "package-name"
    arches = ", ".join(cfg.architectures)
    sources_file = _lines(
        "Types: deb",
        f"URIs: {base}/",
        f"Suites: {cfg.suite}",
        f"Components: {cfg.component}",
        f"Signed-By: {KEYRING}",
    )
    key_cmd = _lines(
        "sudo install -d -m 0755 /etc/apt/keyrings",
        f"sudo curl -fsSL {base}/key.gpg -o {KEYRING}",
    )
    sources_cmd = f"sudo tee {SOURCES} >/dev/null <<'EOF'\n{sources_file}\nEOF"
    update_cmd = f"sudo apt update\nsudo apt install {sample}"

    all_in_one = _terminal(
        "bash",
        e(_lines(key_cmd, sources_cmd, "sudo apt update")),
        "Copy the complete install snippet",
    )
    step_key = _terminal("1. key", e(key_cmd), "Copy the key commands")
    step_src = _terminal(SOURCES.rsplit("/", 1)[1], e(sources_cmd), "Copy the sources file command")
    step_apt = _terminal("3. install", e(update_cmd), "Copy the update and install commands")
    verify_cmd = f"gpg --show-keys --fingerprint {KEYRING}"
    remove_cmd = f"sudo rm {SOURCES} {KEYRING}\nsudo apt update"
    pin_cmd = "apt policy neovim"
    why = [
        ("clock", "Always the latest release",
         f"A bot checks every upstream project every {CHECK_HOURS} hours and publishes new releases on its own."),
        ("layers", "One suite for every release",
         "Static or portable builds, so the same repository serves Debian and Ubuntu, old and new."),
        ("shield", "Signed and verifiable",
         "Every index is signed with GPG. Check the fingerprint yourself before you trust the key."),
        ("nobody", "No tracking, no account",
         "Plain static files over HTTPS. No sign-up, no cookies, no analytics, no script on this page that phones home."),
        ("code", "Open and reproducible",
         "Recipes and builder are public. Packages are built from public upstream releases, byte for byte reproducible."),
    ]
    why_html = "".join(
        f'<div class="card">{_icon(icon)}<h3>{e(title)}</h3><p>{e(text)}</p></div>' for icon, title, text in why
    )
    flow = [
        ("Upstream release", "A project publishes a release on GitHub. Nothing is patched."),
        ("Build and sign", f"GitHub Actions, every {CHECK_HOURS} hours: verify checksums, check the licence, build the .deb, sign the index with GPG."),
        ("Store", "Static files in a Cloudflare R2 bucket. Old versions are pruned, packages never change."),
        ("Serve", "Cloudflare CDN over HTTPS. apt only needs plain GET requests."),
    ]
    flow_html = "".join(
        f'<li><span class="n" aria-hidden="true">{i}</span><div><b>{e(t)}</b><span>{e(d)}</span></div></li>'
        for i, (t, d) in enumerate(flow, 1)
    )
    pretty = e(_pretty_fingerprint(fingerprint))
    meta_desc = e(cfg.description)
    title = f"{cfg.origin}: up-to-date developer tools for Debian and Ubuntu"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{meta_desc}">
<meta name="theme-color" content="#fbfbfa" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0a1112" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:url" content="{e(base)}/">
<meta name="twitter:card" content="summary">
<link rel="icon" href="{FAVICON}">
<style>{CSS}</style></head><body>
<a class="skip" href="#main">Skip to content</a>
<div class="hero"><div class="wrap">
<header class="top">
<a class="brand" href="#top"><svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#0f766e"/><path d="M9 11l6 5-6 5M17 22h7" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>{e(cfg.origin)}</a>
<nav aria-label="Main"><ul>
<li><a href="#packages">Packages</a></li><li><a href="#install">Install</a></li><li><a href="#trust">Trust</a></li><li><a href="#faq">FAQ</a></li>
<li><a class="gh" href="{SOURCE_URL}">Source</a></li>
</ul></nav></header>
<div class="hero-grid" id="top">
<div>
<span class="pill"><i></i>Signed &middot; static &middot; free</span>
<h1>Up-to-date tools for <em>Debian</em> and <em>Ubuntu</em></h1>
<p class="lead">The latest upstream releases of the developer tools your distribution ships late or not at all.
One repository, signed with GPG, served as plain static files. No account, no cost.</p>
<div class="cta"><a class="btn primary" href="#install">Add the repository</a><a class="btn" href="#packages">Browse {count} packages</a></div>
<ul class="stats">
<li><b>{count}</b><span>packages</span></li>
<li><b>{e(str(len(cfg.architectures)))}</b><span>architectures</span></li>
<li><b>{CHECK_HOURS} h</b><span>update check</span></li>
</ul></div>
<div>{all_in_one}</div>
</div></div></div>
<main id="main">

<section id="why"><div class="wrap">
<div class="head"><p class="eyebrow">Why this repository</p><h2>Boring infrastructure, fresh software</h2>
<p class="sub">Debian and Ubuntu freeze versions for years. This repository does not.</p></div>
<div class="grid why">{why_html}</div>
</div></section>

<section id="install" class="alt"><div class="wrap">
<div class="head"><p class="eyebrow">Install</p><h2>Three steps, about a minute</h2>
<p class="sub">Works on current Debian and Ubuntu releases. Run these as a normal user; they use <code>sudo</code>.</p></div>
<ol class="steps">
<li><div><h3>Add the signing key</h3><p>apt checks every download against this key. It is stored in its own keyring, so it is trusted for this repository only.</p></div>{step_key}</li>
<li><div><h3>Add the source</h3><p>A small DEB822 file that tells apt where to look and which key to trust.</p>
<dl><dt>URIs</dt> <dd>where the repository lives.</dd>
<dt>Suites</dt> <dd><code>{e(cfg.suite)}</code>, the only suite. It serves every release.</dd>
<dt>Components</dt> <dd><code>{e(cfg.component)}</code>.</dd>
<dt>Signed-By</dt> <dd>pins the key from step 1 to this source.</dd></dl></div>{step_src}</li>
<li><div><h3>Update and install</h3><p>Install anything from the catalogue below, then upgrade with the rest of your system from now on.</p></div>{step_apt}</li>
</ol>
</div></section>

<section id="packages"><div class="wrap">
<div class="head"><p class="eyebrow">Catalogue</p><h2>{count} tools, current today</h2>
<p class="sub">Versions shown are the latest published. The same data is available as <a href="{e(base)}/index.json"><code>index.json</code></a>.</p></div>
{grid}
{transitional}
</div></section>

<section id="systems" class="alt"><div class="wrap">
<div class="head"><p class="eyebrow">Compatibility</p><h2>Supported systems</h2>
<p class="sub">One suite serves everything. Packages that need a newer system say so on their card, and apt refuses to install them where they would not run.</p></div>
<div class="os">
<div class="card"><h3>Distributions</h3><ul><li>Debian 12 and newer</li><li>Ubuntu 22.04 and newer (some tools need a newer one, see the cards)</li><li>Derivatives such as Linux Mint and Pop!_OS</li></ul></div>
<div class="card"><h3>Architectures</h3><ul><li><code>amd64</code>: PCs and most servers</li><li><code>arm64</code>: Raspberry Pi, ARM servers and laptops</li><li><code>all</code>: architecture-independent packages, for example a Python zipapp</li></ul></div>
<div class="card"><h3>Published here</h3><ul><li>Suite <code>{e(cfg.suite)}</code>, component <code>{e(cfg.component)}</code></li><li>Architectures: {e(arches)}</li><li>The newest {e(str(cfg.retain))} versions of each package</li></ul></div>
</div></div></section>

<section id="trust"><div class="wrap">
<div class="head"><p class="eyebrow">How it works</p><h2>Static files you can verify</h2>
<p class="sub">No server runs code when you install. The repository is a folder of files, built in public and signed before it is uploaded.</p></div>
<div class="two">
<ol class="flow">{flow_html}</ol>
<div>
<h3>Signing key fingerprint</h3>
<p class="mut" style="margin-top:.5rem">After step 1, print the fingerprint of the key apt will use. It must match this one exactly.</p>
<div class="fp-row"><div class="fp" aria-label="Signing key fingerprint">{pretty}</div>{_copy_button("Copy the fingerprint without spaces", text=fingerprint, light=True)}</div>
{_terminal("verify", e(verify_cmd), "Copy the verify command")}
<p class="mut" style="margin-top:1rem">This page and the key come from the same host. To check the key independently, compare it with the copy in the
<a href="{SOURCE_URL}/blob/main/keys/rafaelvieiras-apt.asc">source repository</a>.</p>
<ul class="links">
<li><a href="{SOURCE_URL}">Source code</a></li>
<li><a href="{e(base)}/index.json"><code>index.json</code></a></li>
<li><a href="{e(base)}/key.asc"><code>key.asc</code></a></li>
<li><a href="{e(base)}/dists/{e(cfg.suite)}/InRelease"><code>InRelease</code></a></li>
</ul></div>
</div></div></section>

<section id="faq" class="alt"><div class="wrap">
<div class="head"><p class="eyebrow">FAQ</p><h2>Questions you may have</h2></div>
<div class="faq">
<details><summary>How do updates arrive?</summary><div>
<p>Every {CHECK_HOURS} hours a GitHub Actions job looks for new upstream releases, builds and signs what changed and uploads it. On your side it is the normal routine: <code>sudo apt update &amp;&amp; sudo apt upgrade</code>.</p></div></details>
<details><summary>What if my distribution ships the same package?</summary><div>
<p>apt installs the highest version it can see. These packages usually carry the newer upstream version, so they win. Check which one apt would pick with:</p>
{_terminal("bash", e(pin_cmd), "Copy the apt policy command")}
<p>To keep the distribution version of a package, pin it with a file in <code>/etc/apt/preferences.d/</code>.</p></div></details>
<details><summary>Where do the binaries come from?</summary><div>
<p>From each project's own GitHub release, checksummed and repackaged without changes. Ghostty is the exception: it publishes no Linux binaries, so its <code>.deb</code> comes from the community build mkasberg/ghostty-ubuntu.</p></div></details>
<details><summary>How do I remove the repository?</summary><div>
<p>Delete the source and the key, then refresh. Packages you already installed stay on your system; they just stop receiving updates.</p>
{_terminal("bash", e(remove_cmd), "Copy the remove commands")}</div></details>
<details><summary>Can I request a package?</summary><div>
<p>Yes. <a href="{SOURCE_URL}/issues/new">Open an issue</a> with the upstream link. It needs GitHub releases with Linux builds and a licence that allows redistribution. Static builds are preferred.</p></div></details>
<details><summary>Does this site track me?</summary><div>
<p>No cookies, no analytics, no external requests. It is one HTML file. Like any website, the host (Cloudflare) handles the HTTPS requests themselves.</p></div></details>
</div></div></section>

</main>
<footer><div class="wrap">
<div><b>{e(cfg.origin)}</b><br>Generated <time datetime="{e(state.get("generated", ""))}">{e(_stamp(state.get("generated", "")))}</time></div>
<ul><li><a href="{SOURCE_URL}">Source on GitHub</a></li><li><a href="{SOURCE_URL}/blob/main/LICENSE">MIT licence</a></li><li><a href="{e(base)}/index.json">index.json</a></li></ul>
<p>Packaged software keeps its own licence.</p>
</div></footer>
<div id="live" class="sr" role="status" aria-live="polite"></div>
<script>{JS}</script>
</body></html>
"""
