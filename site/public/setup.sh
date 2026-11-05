#!/bin/sh
# setup.sh: add the rafaelvieiras apt repository to this machine.
#
#   curl -fsSL https://apt.rafaelvieiras.com/setup.sh | sudo sh
#   curl -fsSL https://apt.rafaelvieiras.com/setup.sh | sudo sh -s -- --uninstall
#
# What it does, and nothing else:
#   1. downloads the signing key and checks its fingerprint (when gpg is installed);
#   2. writes the key to        /etc/apt/keyrings/rafaelvieiras-apt.gpg
#   3. writes the source to     /etc/apt/sources.list.d/rafaelvieiras-apt.sources
#   4. refreshes the package lists of this one source.
#
# It never installs a package. Afterwards, use apt as usual: sudo apt install <package>
#
# Plain POSIX sh. Read it before you run it: https://apt.rafaelvieiras.com/setup.sh
# Source: https://github.com/rafaelvieiras/apt (site/public/setup.sh)

set -eu

# Fixed values. tests/test_aptrepo.py checks them against repo.toml and keys/.
BASE_URL="${RAFAELVIEIRAS_APT_URL:-https://apt.rafaelvieiras.com}"
SUITE="stable"
COMPONENT="main"
FINGERPRINT="D7A3DA0BEA6E67AFADA5C504675F04D1172008F5"
# sha256 of key.gpg, the fallback check when gpg is not installed.
KEY_SHA256="5e61536ca35fea25a42a70ec97e418b423a0b12528a8d20e8e2ac50c069e5515"
KEYRING="/etc/apt/keyrings/rafaelvieiras-apt.gpg"
SOURCES="/etc/apt/sources.list.d/rafaelvieiras-apt.sources"

DRY_RUN=0
UNINSTALL=0
DO_UPDATE=1
SUDO=""
TMP=""

if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD=$(printf '\033[1m'); YELLOW=$(printf '\033[33m'); RED=$(printf '\033[31m'); RESET=$(printf '\033[0m')
else
    BOLD=""; YELLOW=""; RED=""; RESET=""
fi

say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*" >&2; }
note() { printf '    %s\n' "$*" >&2; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: setup.sh [options]

Adds the rafaelvieiras apt repository (signed, static) to Debian or Ubuntu.
It sets up the source and the key, and nothing else: no package is installed.

Options:
  -n, --dry-run     show what would happen; change nothing, download nothing
      --no-update   do not run apt-get update afterwards
      --uninstall   remove the source and the key (installed packages stay)
  -h, --help        show this help

Examples:
  sudo sh setup.sh
  sudo sh setup.sh --uninstall

Environment:
  RAFAELVIEIRAS_APT_URL   use another base URL (for testing a mirror)
  NO_COLOR                turn colours off
EOF
}

cleanup() {
    if [ -n "$TMP" ]; then
        rm -rf "$TMP"
    fi
}

# Run a command, or only show it under --dry-run.
run() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '    + %s\n' "$*" >&2
    else
        "$@"
    fi
}

# Like run, but through sudo when we are not root.
as_root() {
    if [ -n "$SUDO" ]; then
        run "$SUDO" "$@"
    else
        run "$@"
    fi
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help) usage; exit 0 ;;
            -n|--dry-run) DRY_RUN=1 ;;
            --no-update) DO_UPDATE=0 ;;
            --uninstall|--remove) UNINSTALL=1 ;;
            *) usage >&2; printf '\nunknown argument: %s\n' "$1" >&2; exit 2 ;;
        esac
        shift
    done
}

check_system() {
    command -v apt-get >/dev/null 2>&1 || die "apt-get not found. This repository is for Debian, Ubuntu and their derivatives."

    family=""
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        family=$(. /etc/os-release && printf '%s %s' "${ID:-}" "${ID_LIKE:-}")
    fi
    case " $family " in
        *" debian "*|*" ubuntu "*) ;;
        *) warn "this does not look like Debian or Ubuntu (found: ${family:-unknown}). Continuing because apt-get exists." ;;
    esac

    if command -v dpkg >/dev/null 2>&1; then
        arch=$(dpkg --print-architecture)
        case "$arch" in
            amd64|arm64) ;;
            *) die "this repository serves amd64 and arm64 only; this machine is $arch." ;;
        esac
    fi
}

check_privileges() {
    if [ "$(id -u)" = 0 ]; then
        return
    fi
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
        return
    fi
    if [ "$DRY_RUN" = 1 ]; then
        return
    fi
    die "this needs root. Run it as root, or install sudo."
}

# download URL DESTINATION
download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 --connect-timeout 15 --max-time 120 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --tries=3 --timeout=30 -O "$2" "$1"
    else
        die "neither curl nor wget found. Install curl (and ca-certificates) first, then run this again."
    fi
}

# The key is trusted for this repository only (Signed-By), but check it anyway
# against the fingerprint that the website and the README publish. Without gpg
# (minimal images) fall back to the checksum of the key file.
verify_key() {
    if command -v gpg >/dev/null 2>&1; then
        mkdir -m 700 "$TMP/gnupg"
        found=$(GNUPGHOME="$TMP/gnupg" gpg --batch --with-colons --show-keys "$1" 2>/dev/null |
            awk -F: '$1 == "fpr" { print $10; exit }')
        if [ "$found" != "$FINGERPRINT" ]; then
            die "the downloaded key has fingerprint '${found:-none}', expected $FINGERPRINT. Nothing was installed."
        fi
        note "key fingerprint verified: $FINGERPRINT"
    elif command -v sha256sum >/dev/null 2>&1; then
        found=$(sha256sum "$1" | awk '{ print $1 }')
        if [ "$found" != "$KEY_SHA256" ]; then
            die "the downloaded key has sha256 '$found', expected $KEY_SHA256. Nothing was installed."
        fi
        note "key checksum verified (gpg is not installed, so the fingerprint was not read)"
    else
        warn "neither gpg nor sha256sum found; the key was not checked."
        note "Expected fingerprint: $FINGERPRINT"
    fi
}

render_sources() {
    cat <<EOF
Types: deb
URIs: $BASE_URL/
Suites: $SUITE
Components: $COMPONENT
Signed-By: $KEYRING
EOF
}

refresh_lists() {
    # Refresh only this source. It is faster, and a broken third-party repository
    # elsewhere on the machine cannot make this step fail.
    say "Refreshing the package lists"
    if run $SUDO apt-get update \
        -o Dir::Etc::sourcelist="sources.list.d/rafaelvieiras-apt.sources" \
        -o Dir::Etc::sourceparts="-" \
        -o APT::Get::List-Cleanup="0"; then
        return
    fi
    warn "the targeted update failed; trying a full apt-get update"
    run $SUDO apt-get update
}

do_install() {
    say "Adding the rafaelvieiras apt repository ($BASE_URL)"
    if [ "$BASE_URL" != "https://apt.rafaelvieiras.com" ]; then
        warn "using a custom base URL: $BASE_URL"
    fi

    TMP=$(mktemp -d)
    if [ "$DRY_RUN" = 1 ]; then
        note "would download $BASE_URL/key.gpg and check it against $FINGERPRINT"
        render_sources > "$TMP/sources"
    else
        download "$BASE_URL/key.gpg" "$TMP/key.gpg"
        [ -s "$TMP/key.gpg" ] || die "the downloaded key is empty."
        verify_key "$TMP/key.gpg"
        render_sources > "$TMP/sources"
    fi

    say "Writing $KEYRING"
    as_root install -d -m 0755 "$(dirname "$KEYRING")"
    as_root install -m 0644 "$TMP/key.gpg" "$KEYRING"

    say "Writing $SOURCES"
    if [ "$DRY_RUN" = 0 ] && [ -f "$SOURCES" ] && cmp -s "$TMP/sources" "$SOURCES"; then
        note "already up to date"
    else
        as_root install -m 0644 "$TMP/sources" "$SOURCES"
    fi
    if [ "$DRY_RUN" = 1 ]; then
        render_sources | sed 's/^/        /' >&2
    fi

    if [ "$DO_UPDATE" = 1 ]; then
        refresh_lists
    fi

    say "Done. The repository is ready; nothing was installed."
    note "Install something with:  sudo apt install <package>"
    note "Everything available:    $BASE_URL/packages"
    note "Remove the repository with: curl -fsSL $BASE_URL/setup.sh | sudo sh -s -- --uninstall"
}

do_uninstall() {
    say "Removing the rafaelvieiras apt repository"
    as_root rm -f "$SOURCES" "$KEYRING"
    if [ "$DO_UPDATE" = 1 ]; then
        say "Refreshing the package lists"
        run $SUDO apt-get update
    fi
    say "Done."
    note "Packages you installed from it stay on this machine; they no longer get updates."
}

main() {
    parse_args "$@"
    trap cleanup EXIT
    trap 'exit 130' INT TERM HUP
    check_system
    check_privileges
    if [ "$UNINSTALL" = 1 ]; then
        do_uninstall
    else
        do_install
    fi
}

# Everything above is a definition. Nothing runs until this line has been read,
# so a download that stops half way never executes half a script.
main "$@"
