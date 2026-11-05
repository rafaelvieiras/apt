// Everything the pages need, in one place: the data file from `python -m aptrepo site-data`
// plus a few constants that are fixed by the repository layout.
import fs from "node:fs";
import path from "node:path";

export const SOURCE_URL = "https://github.com/rafaelvieiras/apt";
export const CHECK_HOURS = 6; // keep in sync with the cron in .github/workflows/publish.yml
export const KEYRING = "/etc/apt/keyrings/rafaelvieiras-apt.gpg";
export const SOURCES = "/etc/apt/sources.list.d/rafaelvieiras-apt.sources";
// Shown first on the home page when they exist; anything else fills the strip.
const FEATURED = ["neovim", "ghostty", "yazi", "ripgrep"];

export interface Pkg {
  name: string;
  version: string;
  debVersion: string;
  released: string;
  arches: string[];
  license: string;
  homepage: string;
  description: string;
  note: string;
  transitional: boolean;
}

export interface SiteData {
  schema: number;
  sample?: boolean;
  generated: string;
  indexGenerated: string;
  repo: {
    name: string;
    description: string;
    baseUrl: string;
    suite: string;
    component: string;
    architectures: string[];
    retain: number;
  };
  fingerprint: { raw: string; pretty: string };
  packages: Pkg[];
}

function locate(): { file: string; sample: boolean } {
  const wanted = process.env.SITE_DATA;
  if (wanted) {
    const file = path.resolve(wanted);
    if (!fs.existsSync(file)) throw new Error(`SITE_DATA points to a missing file: ${file}`);
    return { file, sample: false };
  }
  const real = path.resolve("src/data/site-data.json");
  if (fs.existsSync(real)) return { file: real, sample: false };
  console.warn("[site] src/data/site-data.json not found: using src/data/sample.json (sample data, do not publish)");
  return { file: path.resolve("src/data/sample.json"), sample: true };
}

function load(): SiteData {
  const { file } = locate();
  const data = JSON.parse(fs.readFileSync(file, "utf8")) as SiteData;
  if (data.schema !== 1) throw new Error(`${file}: unsupported site-data schema ${data.schema}`);
  for (const key of ["repo", "fingerprint", "packages", "generated"] as const) {
    if (!data[key]) throw new Error(`${file}: missing "${key}"`);
  }
  return data;
}

export const data = load();
/** True when built from sample.json: the pages carry a marker and the uploader refuses them. */
export const isSample = locate().sample || data.sample === true;
export const repo = data.repo;
export const packages = data.packages.filter((p) => !p.transitional);
export const transitional = data.packages.filter((p) => p.transitional);

export const featured: Pkg[] = [
  ...FEATURED.map((n) => packages.find((p) => p.name === n)).filter((p): p is Pkg => Boolean(p)),
  ...packages.filter((p) => !FEATURED.includes(p.name)),
].slice(0, 4);

/** `2026-05-20T06:17:03Z` -> `2026-05-20 06:17 UTC` */
export function stamp(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso || "");
  return m ? `${m[1]} ${m[2]} UTC` : iso || "unknown";
}

/** `2026-05-20T06:17:03Z` -> `2026-05-20` (empty when unknown) */
export function day(iso: string): string {
  return /^(\d{4}-\d{2}-\d{2})/.exec(iso || "")?.[1] ?? "";
}

/** The commands shown on the install steps. Always built from the data, never typed twice. */
export function install() {
  const base = repo.baseUrl;
  const sample = featured.slice(0, 3).map((p) => p.name).join(" ") || "package-name";
  const key = [
    "sudo install -d -m 0755 /etc/apt/keyrings",
    `sudo curl -fsSL ${base}/key.gpg -o ${KEYRING}`,
  ].join("\n");
  const sourcesFile = [
    "Types: deb",
    `URIs: ${base}/`,
    `Suites: ${repo.suite}`,
    `Components: ${repo.component}`,
    `Signed-By: ${KEYRING}`,
  ].join("\n");
  const source = `sudo tee ${SOURCES} >/dev/null <<'EOF'\n${sourcesFile}\nEOF`;
  return {
    key,
    source,
    update: `sudo apt update\nsudo apt install ${sample}`,
    all: [
      "# 1. trust the signing key",
      key,
      "# 2. add the repository",
      source,
      "# 3. install something",
      `sudo apt update && sudo apt install ${sample}`,
    ].join("\n"),
    hero: ["# add the repository (key + source, fingerprint checked)", `curl -fsSL ${base}/setup.sh | sudo sh`, "# then install anything from it, as usual", `sudo apt install ${sample}`].join("\n"),
    quick: `curl -fsSL ${base}/setup.sh | sudo sh`,
    quickRemove: `curl -fsSL ${base}/setup.sh | sudo sh -s -- --uninstall`,
    verify: `gpg --show-keys --fingerprint ${KEYRING}`,
    remove: `sudo rm ${SOURCES} ${KEYRING}\nsudo apt update`,
    policy: `apt policy ${featured[0]?.name ?? "package-name"}`,
  };
}
