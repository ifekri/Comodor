#!/bin/sh
# Does the fixed lookup refuse a Windows shim and accept a real tool?
#
# The failure being reproduced, reported from Debian under WSL:
#
#   /mnt/c/Users/X4btc/scoop/shims/pipx: 3: cmd.exe: Exec format error
#
# WSL inherits the Windows PATH, so `command -v pipx` answers with a Windows
# shim on a mounted drive. Nothing checked it could run.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SCRIPT="$HERE/../lib/scripts/install.sh"
LAB="${TMPDIR:-/tmp}/comodor-lookup-check.$$"

trap 'rm -rf "$LAB"' EXIT INT TERM
rm -rf "$LAB"
mkdir -p "$LAB/mnt/c/shims" "$LAB/real" "$LAB/plain"

# A shim of the kind scoop leaves behind: a real file, executable, that Linux
# cannot exec because its interpreter is a Windows binary.
printf '#!/mnt/c/Windows/System32/cmd.exe\n@echo off\n' > "$LAB/mnt/c/shims/pipx"
chmod +x "$LAB/mnt/c/shims/pipx"

# A tool that works.
printf '#!/bin/sh\necho "uv 0.5.0"\n' > "$LAB/real/uv"
chmod +x "$LAB/real/uv"

# A tool with no --version at all, which must still count as runnable.
printf '#!/bin/sh\nexit 2\n' > "$LAB/plain/oddtool"
chmod +x "$LAB/plain/oddtool"

# Just the two functions under test.
sed -n '/^runnable() /,/^}/p;/^find_tool() /,/^}/p' "$SCRIPT" > "$LAB/lookup.sh"

fails=0
check() {
    want=$1; label=$2; path=$3
    if (. "$LAB/lookup.sh"; TOOL_DIRS=""; runnable "$path") >/dev/null 2>&1; then
        got=accepted
    else
        got=refused
    fi
    if [ "$got" = "$want" ]; then
        printf '  OK   %-46s %s\n' "$label" "$got"
    else
        printf '  BUG  %-46s %s (wanted %s)\n' "$label" "$got" "$want"
        fails=$((fails + 1))
    fi
}

echo "runnable():"
check refused  "a Windows shim under /mnt/c"        "$LAB/mnt/c/shims/pipx"
check refused  "anything ending .exe"               "/usr/bin/whatever.exe"
check refused  "a path that does not exist"         "$LAB/nope/pipx"
check accepted "a working tool"                     "$LAB/real/uv"
check accepted "a tool with no --version"           "$LAB/plain/oddtool"

echo
echo "find_tool(), with the Windows shim first on PATH:"
found=$(PATH="$LAB/mnt/c/shims:$LAB/real:$PATH" sh -c \
    ". \"$LAB/lookup.sh\"; TOOL_DIRS=\"\"; find_tool pipx" 2>/dev/null || true)
if [ -z "$found" ]; then
    echo "  OK   pipx is not offered at all"
else
    echo "  BUG  it offered $found"
    fails=$((fails + 1))
fi

found=$(PATH="$LAB/mnt/c/shims:$LAB/real:$PATH" sh -c \
    ". \"$LAB/lookup.sh\"; TOOL_DIRS=\"\"; find_tool uv" 2>/dev/null || true)
case "$found" in
    "$LAB/real/uv") echo "  OK   uv is still found" ;;
    *) echo "  BUG  uv came back as '$found'"; fails=$((fails + 1)) ;;
esac

echo
[ "$fails" -eq 0 ] && echo "all correct" || echo "$fails wrong"
exit "$fails"
