#!/bin/sh
# Comodor installer — macOS, Linux, BSD.
#
#   curl -fsSL https://comodor.ai/install.sh | sh
#
# Written for POSIX sh, not bash, so it runs on Alpine and on the minimal
# shells inside containers.
#
# The job of this script is to finish. Somebody running one line from a web
# page has not agreed to debug anything, so it installs what it needs — an
# isolated environment, a package manager, a Python — rather than stopping to
# explain what they should have had already. It gives up only when it genuinely
# cannot proceed, and then it names exactly one thing to do next.
#
# Environment:
#   COMODOR_INSTALL_REF     install from a git ref or local path instead of PyPI
#   COMODOR_FORCE_TOOL      pin the method to uv | pipx | venv | pip
#   COMODOR_NO_BOOTSTRAP    never download a tool; fail instead
#   COMODOR_NO_MODIFY_PATH  do not touch the shell profile

set -eu

PACKAGE="comodor"
COMMAND="comodor"
PYTHON_MIN_MINOR=11
REPO="https://github.com/ifekri/Comodor"
SITE="https://comodor.ai"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV_DIR="$DATA_HOME/comodor/venv"
BIN_DIR="$HOME/.local/bin"
INSTALLED=""
PROFILE_WRITTEN=""
PATH_STATE=""
TOOL=""
UV=""
PIPX=""
PYTHON=""
PYTHON_CANDIDATES=""
VENV_PYTHON=""

# ------------------------------------------------------------------ output --

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD=$(printf '\033[1m')
    DIM=$(printf '\033[2m')
    AMBER=$(printf '\033[38;5;208m')
    RED=$(printf '\033[31m')
    GREEN=$(printf '\033[32m')
    RESET=$(printf '\033[0m')
else
    BOLD='' DIM='' AMBER='' RED='' GREEN='' RESET=''
fi

say() { printf '%s\n' "$*"; }
step() { printf '%s>%s %s\n' "$AMBER" "$RESET" "$*"; }
note() { printf '%s  %s%s\n' "$DIM" "$*" "$RESET"; }
# Octal, not \xNN: hex escapes are a bash extension, and /bin/sh on Debian and
# Ubuntu is dash, which prints them literally.
ok() { printf '%s\342\234\223%s %s\n' "$GREEN" "$RESET" "$*"; }

die() {
    printf '\n%serror:%s %s\n' "$RED" "$RESET" "$1" >&2
    shift
    for line in "$@"; do printf '  %s\n' "$line" >&2; done
    printf '\n  Nothing was installed. Please report this at %s/issues\n' "$REPO" >&2
    printf '  and include the output above — it says where it stopped.\n' >&2
    exit 1
}

has() { command -v "$1" >/dev/null 2>&1; }

# ------------------------------------------------------------------ lookup --

# Where tools put themselves. This list exists because of a real failure: a
# `curl | sh` pipeline runs a non-interactive shell that never reads the user's
# profile, so PATH is the bare system one. Somebody who had already installed
# uv watched this script decide uv was unavailable and then fail on a fallback.
# The right tool was on the disk the whole time — just invisible.
TOOL_DIRS="$BIN_DIR $HOME/.cargo/bin $HOME/bin
           /opt/homebrew/bin /usr/local/bin /home/linuxbrew/.linuxbrew/bin"

find_tool() {
    if command -v "$1" 2>/dev/null; then
        return 0
    fi
    for dir in $TOOL_DIRS; do
        if [ -x "$dir/$1" ]; then
            printf '%s\n' "$dir/$1"
            return 0
        fi
    done
    return 1
}

# ------------------------------------------------------------------ system --

detect_platform() {
    os=$(uname -s 2>/dev/null || echo unknown)
    arch=$(uname -m 2>/dev/null || echo unknown)
    case "$os" in
        Darwin) PLATFORM="macOS" ;;
        Linux) PLATFORM="Linux" ;;
        FreeBSD | OpenBSD | NetBSD) PLATFORM="$os" ;;
        MINGW* | MSYS* | CYGWIN*)
            # A POSIX shell driving a Windows Python: the install itself works,
            # but the PATH advice below would name directories this shell can
            # see and cmd.exe cannot. PowerShell is the better route — with a
            # way past it, because a guard with no override strands somebody.
            if [ -z "${COMODOR_ALLOW_MSYS:-}" ]; then
                die "This looks like Windows ($os)." \
                    "Run the PowerShell installer instead:" \
                    "  irm $SITE/install.ps1 | iex" \
                    "" \
                    "To install from this shell anyway: COMODOR_ALLOW_MSYS=1"
            fi
            PLATFORM="Windows ($os)"
            ;;
        *) PLATFORM="$os" ;;
    esac
    ARCH="$arch"
}

# Every interpreter worth considering, one "<minor> <path>" per line, newest
# first and deduplicated by the executable each one really resolves to.
#
# Deliberately not "the first `python3.12` on PATH". A machine can carry two
# interpreters of the same version where only one of them works: on Ubuntu the
# system `/usr/bin/python3.12` cannot build a virtual environment at all — venv
# is a separate package — while a `python3.12` in ~/.local/bin can. Taking the
# first match found the broken one and stopped looking.
list_pythons() {
    seen=""
    listing=""
    for name in python3.14 python3.13 python3.12 python3.11 python3 python; do
        for path in $(locations "$name"); do
            real=$("$path" -c 'import sys; print(sys.executable)' 2>/dev/null) || continue
            case "$seen" in *"|$real|"*) continue ;; esac
            minor=$("$path" -c 'import sys; print(sys.version_info[1] if sys.version_info[0] == 3 else -1)' 2>/dev/null || echo -1)
            case "$minor" in
                '' | *[!0-9-]*) continue ;;
            esac
            [ "$minor" -lt "$PYTHON_MIN_MINOR" ] && continue
            seen="$seen|$real|"
            listing="$listing$minor $path
"
        done
    done
    printf '%s' "$listing" | sort -rn -k1,1
}

# Every place a given interpreter name might live, not just the first.
locations() {
    command -v "$1" 2>/dev/null || true
    for dir in $TOOL_DIRS; do
        [ -x "$dir/$1" ] && printf '%s\n' "$dir/$1"
    done
    return 0
}

find_python() {
    PYTHON_CANDIDATES=$(list_pythons)
    PYTHON=$(printf '%s' "$PYTHON_CANDIDATES" | head -1 | cut -d' ' -f2-)
}

# The newest Python is not necessarily one that can build an environment, so
# this asks each in turn rather than assuming. A here-document rather than a
# pipe on purpose: a pipe would run the loop in a subshell and the answer would
# be thrown away.
pick_venv_python() {
    VENV_PYTHON=""
    while IFS= read -r entry; do
        [ -n "$entry" ] || continue
        path=${entry#* }
        if venv_works "$path"; then
            VENV_PYTHON="$path"
            return 0
        fi
    done <<EOF
$PYTHON_CANDIDATES
EOF
    return 1
}

# PEP 668. A distribution, or a tool that manages its own runtimes, can mark a
# Python off-limits to pip; installing into it then fails with a wall of text
# recommending `--break-system-packages`. That flag is exactly what it sounds
# like and this script will never pass it. The marker is a signal to install
# somewhere else, which is what a virtual environment is for.
externally_managed() {
    "$1" - <<'PYTHON' >/dev/null 2>&1
import os, sys, sysconfig
marker = os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED")
sys.exit(0 if os.path.exists(marker) else 1)
PYTHON
}

in_virtualenv() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' \
        >/dev/null 2>&1
}

# Debian and its derivatives ship `venv` as a separate package, so a perfectly
# good Python can be unable to make an environment. Worth knowing before we
# commit to that route rather than halfway through it.
venv_works() {
    probe="$DATA_HOME/comodor/.venv-probe"
    rm -rf "$probe" 2>/dev/null || true
    mkdir -p "$(dirname "$probe")" 2>/dev/null || return 1

    "$1" -m venv "$probe" >/dev/null 2>&1
    # The exit code is not enough. On Debian without python3-venv the module
    # prints "ensurepip is not available", leaves a half-built directory, and
    # has been observed exiting 0 — so what gets checked is whether the thing
    # it was supposed to build can actually install a package.
    if [ -x "$probe/bin/python" ] &&
       "$probe/bin/python" -m pip --version >/dev/null 2>&1; then
        rm -rf "$probe" 2>/dev/null || true
        return 0
    fi
    rm -rf "$probe" 2>/dev/null || true
    return 1
}

# ----------------------------------------------------------------- install --

target() {
    # PyPI by default; a git ref or a local checkout when asked, which is how
    # people install before the package is published.
    ref="${COMODOR_INSTALL_REF:-}"
    if [ -z "$ref" ]; then
        printf '%s' "$PACKAGE"
        return
    fi
    case "$ref" in
        git+*) printf '%s' "$ref"; return ;;
    esac
    # A local checkout is one that is actually there. Matching on shape alone
    # fails both ways: git refs contain slashes too (`refs/tags/v1`), and a
    # Windows path (`E:/src/comodor`) looks like no POSIX path at all and would
    # otherwise be handed to git as a revision.
    if [ -e "$ref" ]; then
        printf '%s' "$ref"
    else
        printf 'git+%s@%s' "$REPO" "$ref"
    fi
}

# Fetch uv when there is no other way forward. It is a single static binary
# that needs no Python and can fetch a Python itself, which makes it the one
# tool that answers both "nothing here can install packages" and "there is no
# suitable Python at all".
bootstrap_uv() {
    [ -n "${COMODOR_NO_BOOTSTRAP:-}" ] && return 1

    step "Installing uv, a package manager Comodor needs (about 15 MB)"
    note "from https://astral.sh/uv — it fetches a Python too, if one is missing"

    if has curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || return 1
    elif has wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || return 1
    else
        return 1
    fi

    UV=$(find_tool uv 2>/dev/null) || return 1
    return 0
}

install_with_uv() {
    step "Installing with uv"
    "$UV" tool install --force "$(target)" >/dev/null 2>&1 ||
        "$UV" tool install --force "$(target)" || return 1
    BIN_DIR=$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$BIN_DIR")
    INSTALLED="$BIN_DIR/$COMMAND"
    return 0
}

install_with_pipx() {
    step "Installing with pipx"
    "$PIPX" install --force "$(target)" || return 1
    INSTALLED="$BIN_DIR/$COMMAND"
    return 0
}

# The workhorse, and the answer to PEP 668: a virtual environment is never
# itself externally managed, so installing into one is allowed even when the
# Python it was built from refuses everything else. No download, no extra tool,
# and the result is as isolated as anything pipx would have produced.
install_with_venv() {
    step "Creating an isolated environment for Comodor"
    note "$VENV_DIR"

    mkdir -p "$(dirname "$VENV_DIR")" || return 1
    "$PYTHON" -m venv --clear "$VENV_DIR" >/dev/null 2>&1 || true
    # Checked, not assumed, for the same reason as above.
    [ -x "$VENV_DIR/bin/python" ] || return 1
    "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1 || return 1

    step "Installing $PACKAGE"
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    "$VENV_DIR/bin/python" -m pip install --upgrade "$(target)" || return 1

    # A link rather than a copy, so `comodor` on PATH always points at whatever
    # the environment currently holds: an upgrade needs no relinking, and a
    # removal leaves nothing behind that pretends to still work.
    mkdir -p "$BIN_DIR" || return 1
    ln -sf "$VENV_DIR/bin/$COMMAND" "$BIN_DIR/$COMMAND" || return 1
    INSTALLED="$BIN_DIR/$COMMAND"
    return 0
}

install_with_pip() {
    if in_virtualenv "$PYTHON"; then
        # The user activated an environment; that is a statement about where
        # this should go.
        step "Installing with pip (into the active environment)"
        "$PYTHON" -m pip install --upgrade "$(target)" || return 1
        scheme=""
    else
        if externally_managed "$PYTHON"; then
            return 1        # not this route's call to make; the venv handles it
        fi
        step "Installing with pip (user site)"
        "$PYTHON" -m pip install --user --upgrade "$(target)" || return 1
        scheme="user"
    fi
    # Ask Python where the scripts actually went rather than assuming "bin":
    # it is "Scripts" on Windows, and a wrong PATH hint is worse than none.
    BIN_DIR=$(SCHEME="$scheme" "$PYTHON" - <<'PYTHON' 2>/dev/null || printf '%s' "$BIN_DIR"
import os, sysconfig
if os.environ.get("SCHEME") == "user":
    name = "nt_user" if os.name == "nt" else "posix_user"
else:
    name = sysconfig.get_default_scheme()
print(sysconfig.get_path("scripts", name))
PYTHON
)
    INSTALLED="$BIN_DIR/$COMMAND"
    return 0
}

# -------------------------------------------------------------------- PATH --

profile_for_shell() {
    case "${SHELL:-/bin/sh}" in
        */zsh) printf '%s' "${ZDOTDIR:-$HOME}/.zshrc" ;;
        */bash)
            # macOS login shells read .bash_profile and not .bashrc, so writing
            # only to .bashrc there leaves a line no shell ever reads.
            if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && [ -f "$HOME/.bash_profile" ]; then
                printf '%s' "$HOME/.bash_profile"
            else
                printf '%s' "$HOME/.bashrc"
            fi
            ;;
        */fish) printf '%s' "$HOME/.config/fish/config.fish" ;;
        */ksh) printf '%s' "$HOME/.kshrc" ;;
        *) printf '%s' "$HOME/.profile" ;;
    esac
}

on_path() {
    case ":${PATH}:" in
        *":$1:"*) return 0 ;;
        *) return 1 ;;
    esac
}

# Put the directory on PATH for next time, and record in PATH_STATE what
# actually happened. Printing an instruction and calling it done is where
# installers lose people: the command exists, the shell cannot find it, and
# "command not found" reads exactly like a failed install.
#
# Three outcomes, because they need three different sentences. Telling somebody
# to add a line their profile already contains — which this did on the second
# run — makes a correct install look like a broken one.
add_to_path() {
    directory=$1
    PATH_STATE="manual"

    [ -n "${COMODOR_NO_MODIFY_PATH:-}" ] && return 0

    profile=$(profile_for_shell)
    case "$profile" in
        */config.fish) line="fish_add_path \"$directory\"" ;;
        *) line="export PATH=\"$directory:\$PATH\"" ;;
    esac

    if [ -f "$profile" ] && grep -qF "$directory" "$profile" 2>/dev/null; then
        PATH_STATE="present"           # already there, just not in this shell
        PROFILE_WRITTEN="$profile"
        return 0
    fi

    mkdir -p "$(dirname "$profile")" 2>/dev/null || return 0
    {
        printf '\n# Added by the Comodor installer\n'
        printf '%s\n' "$line"
    } >> "$profile" 2>/dev/null || return 0

    PATH_STATE="added"
    PROFILE_WRITTEN="$profile"
    return 0
}

# --------------------------------------------------------------------- run --

# Sets TOOL. Deliberately not `TOOL=$(choose_tool)`: a command substitution
# runs in a subshell, which would swallow the bootstrap's progress output into
# the variable and throw away the UV path it discovers. Both of those happened.
choose_tool() {
    # Ordered by reliability, not speed. Every route above `pip` produces an
    # isolated install that cannot break, and cannot be broken by, anything
    # else on the machine.
    if [ -n "$UV" ]; then
        TOOL=uv
    elif [ -n "$PIPX" ]; then
        TOOL=pipx
    elif pick_venv_python; then
        PYTHON="$VENV_PYTHON"
        TOOL=venv
    elif bootstrap_uv; then
        TOOL=uv
    elif [ -n "$PYTHON" ] && ! externally_managed "$PYTHON"; then
        TOOL=pip
    else
        TOOL=""
    fi
}

main() {
    printf '\n%s%sComodor%s — it learns the way you correct it.\n\n' "$BOLD" "$AMBER" "$RESET"

    detect_platform
    note "$PLATFORM $ARCH"

    UV=$(find_tool uv 2>/dev/null || true)
    PIPX=$(find_tool pipx 2>/dev/null || true)
    find_python
    [ -n "$PYTHON" ] && note "$("$PYTHON" --version 2>&1)"

    TOOL="${COMODOR_FORCE_TOOL:-}"
    [ -n "$TOOL" ] || choose_tool

    if [ -z "$TOOL" ]; then
        die "Could not find, or install, any way to put Comodor on this machine." \
            "" \
            "Any one of these fixes it:" \
            "  * install uv:    curl -LsSf https://astral.sh/uv/install.sh | sh" \
            "  * install pipx:  your package manager has it" \
            "  * on Debian or Ubuntu the venv module is a separate package:" \
            "      sudo apt install python3-venv" \
            "" \
            "Then run this installer again."
    fi

    case "$TOOL" in
        uv)
            [ -n "$UV" ] || UV=$(find_tool uv 2>/dev/null) ||
                die "COMODOR_FORCE_TOOL=uv, but uv is not installed."
            install_with_uv || die "uv could not install $PACKAGE." \
                "The output above says why."
            ;;
        pipx)
            [ -n "$PIPX" ] || PIPX=$(find_tool pipx 2>/dev/null) ||
                die "COMODOR_FORCE_TOOL=pipx, but pipx is not installed."
            install_with_pipx || die "pipx could not install $PACKAGE." \
                "The output above says why."
            ;;
        venv)
            # Forced, so the search still has to happen: the interpreter that
            # was merely newest may be the one that cannot do this.
            if pick_venv_python; then
                PYTHON="$VENV_PYTHON"
            fi
            [ -n "$PYTHON" ] ||
                die "COMODOR_FORCE_TOOL=venv needs Python 3.$PYTHON_MIN_MINOR or newer."
            install_with_venv || die "Could not build an environment for $PACKAGE." \
                "On Debian or Ubuntu this is usually one missing package:" \
                "  sudo apt install python3-venv" \
                "Then run this installer again."
            ;;
        pip)
            [ -n "$PYTHON" ] ||
                die "COMODOR_FORCE_TOOL=pip needs Python 3.$PYTHON_MIN_MINOR or newer."
            install_with_pip || die "pip cannot install into this Python (PEP 668)." \
                "Run the installer without COMODOR_FORCE_TOOL and it will build an" \
                "isolated environment instead, which that rule does not cover."
            ;;
        *) die "Unknown COMODOR_FORCE_TOOL: $TOOL" "Use one of: uv, pipx, venv, pip" ;;
    esac

    # An install that reports success without producing a working command is
    # the failure people waste the most time on, so it is checked — by running
    # the thing, at its real path, rather than by trusting PATH.
    printf '\n'
    version=""
    if [ -n "$INSTALLED" ] && [ -x "$INSTALLED" ]; then
        version=$("$INSTALLED" --version 2>/dev/null || true)
    fi
    if [ -z "$version" ] && has "$COMMAND"; then
        version=$("$COMMAND" --version 2>/dev/null || true)
    fi

    if [ -n "$version" ]; then
        ok "$version"
    else
        die "$PACKAGE was installed but will not run." \
            "That points at a broken Python environment rather than at the" \
            "package. \`$INSTALLED --version\` shows the real error."
    fi

    if ! on_path "$BIN_DIR"; then
        add_to_path "$BIN_DIR"
        say ""
        case "$PATH_STATE" in
            added)
                note "Added $BIN_DIR to your PATH in $PROFILE_WRITTEN"
                note "That applies to new terminals. For this one:"
                say "    export PATH=\"$BIN_DIR:\$PATH\""
                ;;
            present)
                note "$BIN_DIR is already on your PATH in $PROFILE_WRITTEN;"
                note "this shell just started before that. For this one:"
                say "    export PATH=\"$BIN_DIR:\$PATH\""
                ;;
            *)
                say "  ${COMMAND} is installed at ${AMBER}${INSTALLED}${RESET}, which is not on your PATH."
                say "  Add this to your shell profile:"
                say ""
                say "    export PATH=\"$BIN_DIR:\$PATH\""
                ;;
        esac
    fi

    printf '\n'
    say "  ${BOLD}${COMMAND}${RESET}              start the interface"
    say "  ${BOLD}${COMMAND} --demo${RESET}       try it offline, no API key needed"
    say "  ${BOLD}${COMMAND} doctor${RESET}       check what is configured"
    printf '\n'
    note "The first run asks which provider and model to use, once."
    note "$REPO"
    printf '\n'
}

main "$@"
