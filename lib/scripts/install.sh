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
LINKED=""
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

# How wide the terminal is, for deciding whether the wordmark fits. `tput` is
# not on every minimal image, and COLUMNS is not exported by every shell, so
# both are tried and 80 is the answer when neither knows.
term_width() {
    _w=''
    if command -v tput >/dev/null 2>&1; then
        _w=$(tput cols 2>/dev/null || true)
    fi
    [ -n "$_w" ] || _w="${COLUMNS:-80}"
    case "$_w" in ''|*[!0-9]*) _w=80 ;; esac
    printf '%s' "$_w"
}

# The same wordmark the program draws, and the same rule about when to drop
# it: 47 columns, below which ASCII art reflowed by a terminal is not a
# smaller logo, it is rubble.
banner() {
    printf '\n'
    if [ "$(term_width)" -lt 51 ]; then
        printf '%s%sComodor%s %s— it learns the way you correct it%s\n\n' \
            "$BOLD" "$AMBER" "$RESET" "$DIM" "$RESET"
        return
    fi
    printf '%s%s' "$AMBER" "$BOLD"
    printf '%s\n' '   ______                          __          '
    printf '%s\n' '  / ____/___  ____ ___  ____  ____/ /___  _____'
    printf '%s\n' ' / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/'
    printf '%s\n' '/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /    '
    printf '%s\n' '\____/\____/_/ /_/ /_/\____/\__,_/\____/_/     '
    printf '%s' "$RESET"
    printf '%s  it learns the way you correct it%s\n\n' "$DIM" "$RESET"
}

# A rule with a name on it, so the phases of an install read as phases rather
# than as a wall of lines that happen to have scrolled past.
heading() {
    _title="$1"
    _width=$(term_width)
    [ "$_width" -gt 72 ] && _width=72
    _rule=''
    _i=$(( _width - ${#_title} - 5 ))
    [ "$_i" -lt 3 ] && _i=3
    while [ "$_i" -gt 0 ]; do _rule="${_rule}\342\224\200"; _i=$(( _i - 1 )); done
    printf '\n%s%s%s %s' "$DIM" "$(printf '\342\224\200\342\224\200')" "$RESET" "$BOLD"
    printf '%s%s ' "$_title" "$RESET"
    printf '%s%b%s\n\n' "$DIM" "$_rule" "$RESET"
}
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

    # Both files, and for different shells.
    #
    # The rc file is what the terminal in front of you reads. The login profile
    # is what everything else reads - a new terminal, a desktop session, a
    # script. Writing only the rc leaves those without it, and on Debian it is
    # worse than that: `.bashrc` opens with a guard that returns immediately in
    # a non-interactive shell, so a line appended at the end is unreachable
    # even to something that sources the file deliberately. Measured.
    #
    # fish keeps its own path list and needs neither.
    written=""
    for target in "$profile" "$HOME/.profile"; do
        case "$target" in
            */config.fish) [ "$target" = "$profile" ] || continue ;;
        esac
        # Not twice, when the shell's rc *is* the login profile.
        case " $written " in *" $target "*) continue ;; esac

        if [ -f "$target" ] && grep -qF "$directory" "$target" 2>/dev/null; then
            written="$written $target"
            [ -n "$PROFILE_WRITTEN" ] || PROFILE_WRITTEN="$target"
            [ -n "$PATH_STATE" ] && [ "$PATH_STATE" != "manual" ] || PATH_STATE="present"
            continue
        fi

        mkdir -p "$(dirname "$target")" 2>/dev/null || continue
        {
            printf '\n# Added by the Comodor installer\n'
            printf '%s\n' "$line"
        } >> "$target" 2>/dev/null || continue

        written="$written $target"
        PROFILE_WRITTEN="$target"
        PATH_STATE="added"
    done

    [ -n "$written" ] || PATH_STATE="manual"
    return 0
}

# Make the command work *now*, in the terminal that ran this, rather than in
# the next one.
#
# No child process can change its parent shell's PATH; that is POSIX and not
# something to code around. The way to avoid asking for `export` is therefore
# not to change PATH but to not need to - to put the command somewhere the
# shell is already looking.
#
# Measured before writing this: as root, which is how `curl | sh` usually runs,
# /usr/local/bin is on PATH and writable. As an ordinary user in a login shell,
# nothing on PATH is writable at all. The first case can be finished; the
# second cannot be, by anything running here, and says so instead.
link_into_path() {
    # Preference, not "the first writable directory on PATH": /usr/bin is
    # writable in a container and is not ours to put things in.
    for candidate in /usr/local/bin /opt/homebrew/bin "$HOME/bin"; do
        [ "$candidate" = "$BIN_DIR" ] && continue
        on_path "$candidate" || continue
        [ -d "$candidate" ] && [ -w "$candidate" ] || continue
        ln -sf "$INSTALLED" "$candidate/$COMMAND" 2>/dev/null || continue
        # Prove it rather than assume it. A link that does not run is worse
        # than no link: the command appears to exist and fails on use.
        "$candidate/$COMMAND" --version >/dev/null 2>&1 || {
            rm -f "$candidate/$COMMAND" 2>/dev/null
            continue
        }
        LINKED="$candidate/$COMMAND"
        return 0
    done
    return 1
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
    banner
    heading "Checking this machine"

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
        # A link into somewhere already on PATH finishes the job here, with
        # nothing left for anybody to type. Tried first, for that reason.
        if [ -z "${COMODOR_NO_MODIFY_PATH:-}" ] && link_into_path; then
            add_to_path "$BIN_DIR"      # for the future, quietly
            say ""
            note "Linked into $(dirname "$LINKED"), which is on your PATH."
        else
            add_to_path "$BIN_DIR"
            say ""
            case "$PATH_STATE" in
                added|present)
                    note "Every new terminal can run ${BOLD}${COMMAND}${RESET} already."
                    note "This one started before the install, and no installer"
                    note "can reach back into the shell that ran it. For this"
                    note "terminal only:"
                    say ""
                    say "    ${BOLD}export PATH=\"$BIN_DIR:\$PATH\"${RESET}"
                    ;;
                *)
                    say "  ${COMMAND} is installed at ${AMBER}${INSTALLED}${RESET}, which is not on your PATH."
                    say "  Add this to your shell profile:"
                    say ""
                    say "    export PATH=\"$BIN_DIR:\$PATH\""
                    ;;
            esac
        fi
    fi

    offer_setup
}

# Whether there is a terminal to ask a question on.
#
# Under `curl … | sh` stdin is the script itself, so `read` would swallow the
# rest of the installer. The controlling terminal is a different file and can
# be opened directly — where there is one. In a Dockerfile, in CI, in a
# provisioning script, there is not, and the right thing there is to say what
# to run rather than to ask a question nobody can answer.
have_tty() {
    [ -z "${COMODOR_NO_SETUP:-}" ] || return 1
    [ -e /dev/tty ] || return 1
    ( exec 3< /dev/tty ) 2>/dev/null || return 1
    return 0
}

what_next() {
    printf '\n'
    say "  ${BOLD}${COMMAND}${RESET}              start the interface"
    say "  ${BOLD}${COMMAND} setup${RESET}        choose a provider and a model"
    say "  ${BOLD}${COMMAND} --demo${RESET}       try it offline, no API key needed"
    say "  ${BOLD}${COMMAND} doctor${RESET}       check what is configured"
    printf '\n'
    note "$REPO"
    printf '\n'
}

offer_setup() {
    if ! have_tty; then
        # Nothing to ask on. Say what is left to do and finish cleanly, which
        # is what a build needs from an installer.
        what_next
        note "Run ${BOLD}${COMMAND} setup${RESET}${DIM} once to choose a provider and a model."
        printf '\n'
        return 0
    fi

    banner
    heading "One thing left"
    say "  Comodor needs to know which provider and model to use."
    say "  ${DIM}It is a handful of questions and it is saved, so it is asked once.${RESET}"
    printf '\n'
    say "    ${AMBER}1${RESET}  ${BOLD}Set it up now${RESET}${DIM}  — choose a provider and a model${RESET}"
    say "    ${AMBER}2${RESET}  ${BOLD}Not right now${RESET}${DIM} — I will run \`${COMMAND} setup\` later${RESET}"
    printf '\n'

    _reply=''
    printf '  %sChoice%s %s[1]%s: ' "$BOLD" "$RESET" "$DIM" "$RESET"
    # From the terminal, not from stdin: stdin is the installer.
    IFS= read -r _reply < /dev/tty || _reply=''
    case "$(printf '%s' "$_reply" | tr -d '[:space:]')" in
        ''|1|y|Y|yes|Yes|YES)
            printf '\n'
            # The terminal on its stdin too, for the same reason.
            "$INSTALLED" setup < /dev/tty && return 0
            printf '\n'
            note "Setup did not finish. ${BOLD}${COMMAND} setup${RESET}${DIM} picks it up again."
            what_next
            ;;
        *)
            what_next
            note "When you want it: ${BOLD}${COMMAND} setup${RESET}"
            printf '\n'
            ;;
    esac
}

main "$@"
