# Security Policy

This repository builds and signs packages that users install as root. Treat
reports about it seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's [private vulnerability
reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(the **Security** tab → **Report a vulnerability**), or by email to
**hello@rafaelvieiras.com**.

Please include what you found, how to reproduce it, and which package or file is affected.

## What is in scope

- Anything that lets a third party publish or alter a package or index.
- Signing key handling, CI secrets exposure, or a path from a pull request to the signing key.
- A published package that does not match its upstream release.

## Trust model

- Packages are repackaged from public upstream GitHub releases. Upstream checksums
  (GitHub asset digests) are verified before building.
- The repository is signed with a single key. Its fingerprint is printed at
  <https://apt.rafaelvieiras.com/> and must match what you install.
- If the key is ever compromised, a new key and a notice will be published here
  and on the site. Clients then replace `/etc/apt/keyrings/rafaelvieiras-apt.gpg`.

## Supported versions

Only the latest published version of each package is supported.
