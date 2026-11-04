# Setup

One-time steps to bring the repository online. Everything after this is automatic.

## 1. Signing key

Create a dedicated key. It signs only this repository.

```bash
export GNUPGHOME="$(mktemp -d)"   # throw-away keyring, nothing touches ~/.gnupg
gpg --quick-generate-key "rafaelvieiras apt <hello@rafaelvieiras.com>" ed25519 sign never
gpg --armor --export-secret-keys "rafaelvieiras apt" > apt-private.asc   # -> Bitwarden
gpg --armor --export "rafaelvieiras apt" > keys/rafaelvieiras-apt.asc    # -> commit
gpg --fingerprint "rafaelvieiras apt"
```

- Store `apt-private.asc` (and the passphrase, if you set one) in Bitwarden, then delete the file.
- Commit `keys/rafaelvieiras-apt.asc`. The publisher refuses to run if the secret key
  does not match this public key.
- Back the key up. If it is lost, every client has to install a new one.

## 2. R2 bucket and domain

```bash
export CLOUDFLARE_ACCOUNT_ID=<account id>
npx wrangler r2 bucket create apt
npx wrangler r2 bucket domain add apt --domain apt.rafaelvieiras.com \
  --zone-id <zone id of rafaelvieiras.com> --min-tls 1.2
```

The domain command creates the DNS record and certificate. Do **not** enable the
`r2.dev` public URL; the custom domain is the only entry point.

### Cache rules (keeps it free under load)

The publisher already sets `Cache-Control` on every object (`pool/` and `by-hash/`:
one year, immutable; everything else: five minutes). For the Cloudflare edge to honour
it, add one Cache Rule in the dashboard for `apt.rafaelvieiras.com`:

- **If** hostname equals `apt.rafaelvieiras.com`
- **Then** *Eligible for cache*, **Edge TTL** = *Use cache-control header if present*,
  **Browser TTL** = *Respect origin*.

Without that rule Cloudflare does not cache `.gz`, `.xz`, `.deb` or extensionless
files such as `Release` by default.

Do **not** enable Cache Reserve (it is paid). Cache Rules and Transform Rules are free
(10 of each on the Free plan).

### Landing page on `/` (optional)

R2 does not serve `index.html` for `/`. Add a Transform Rule (Rules → Transform Rules →
Rewrite URL) with the filter `(http.host eq "apt.rafaelvieiras.com" and http.request.uri.path eq "/")`
and **Rewrite path** to the static value `/index.html`.

Both conditions are required. With the path condition missing, every URL is rewritten to the
landing page and `apt update` breaks.

## 3. R2 API token

Dashboard → R2 → **Manage API tokens** → create a token with **Object Read & Write**,
scoped to the `apt` bucket only. Note the Access Key ID, the Secret and the S3 endpoint
(`https://<account id>.r2.cloudflarestorage.com`).

## 4. GitHub secrets and variables

```bash
gh secret set APT_GPG_PRIVATE_KEY < apt-private.asc
gh secret set APT_GPG_PASSPHRASE            # only if the key has one
gh secret set R2_ACCESS_KEY_ID
gh secret set R2_SECRET_ACCESS_KEY
gh variable set R2_BUCKET --body apt
gh variable set R2_ENDPOINT --body https://<account id>.r2.cloudflarestorage.com
```

Pull requests from forks cannot read these secrets. Keep it that way: do not use
`pull_request_target` in the workflows.

## 5. First publish

```bash
gh workflow run publish.yml
```

## Verify

`apt` is the real test. In a clean container:

```bash
docker run --rm -it ubuntu:24.04 bash -c '
  apt-get update -qq && apt-get install -y -qq curl ca-certificates
  curl -fsSL https://apt.rafaelvieiras.com/key.gpg -o /etc/apt/keyrings/rafaelvieiras-apt.gpg
  printf "Types: deb\nURIs: https://apt.rafaelvieiras.com/\nSuites: stable\nComponents: main\nSigned-By: /etc/apt/keyrings/rafaelvieiras-apt.gpg\n" > /etc/apt/sources.list.d/r.sources
  apt-get update && apt-get install -y neovim yazi && nvim --version | head -1'
```

Check caching on the edge:

```bash
curl -sI https://apt.rafaelvieiras.com/pool/main/y/yazi/yazi_26.9.1-1_amd64.deb | grep -iE 'cache-control|cf-cache-status'
```

`curl -I` sends `HEAD`, which Cloudflare never stores, so it always says `DYNAMIC`.
Test with `GET`:

```bash
for i in 1 2; do curl -s -D - -o /dev/null https://apt.rafaelvieiras.com/index.json | grep -i cf-cache-status; done
# second line should say HIT
```

## Rotating the key

Generate a new key, replace `keys/rafaelvieiras-apt.asc` and the `APT_GPG_*` secrets,
then run the workflow with `force_index`. Announce it in `SECURITY.md`; clients must
re-download `key.gpg`.
