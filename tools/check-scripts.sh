#!/bin/sh
# Everything that must be true of the install scripts before they go out.
#
# Each check here exists because the corresponding mistake reached a real user.
# Run it before deploying:  sh tools/check-scripts.sh
#
# What it cannot check is behaviour. Syntax and encoding are necessary, not
# sufficient — see DEPLOY.md for the scenarios that need a real machine.

set -u

DIR=$(dirname "$0")/../lib/scripts
SH="$DIR/install.sh"
PS="$DIR/install.ps1"
FAIL=0

report() {
    if [ "$1" = "0" ]; then
        printf '  ok    %s\n' "$2"
    else
        printf '  FAIL  %s\n' "$2"
        FAIL=$((FAIL + 1))
    fi
}

printf '\ninstall.sh\n'

sh -n "$SH" 2>/dev/null
report $? "parses as POSIX sh"

# A CRLF here is fatal and silent: /bin/sh reads the carriage return as part of
# the last token, so `set -eu` becomes `set -eu\r` and dash reports
# "Illegal option -" before the script prints a single character. This shipped.
if od -c "$SH" | grep -q '\\r'; then
    report 1 "has no CRLF line endings"
else
    report 0 "has no CRLF line endings"
fi

head -1 "$SH" | grep -q '^#!/bin/sh$'
report $? "starts with a POSIX shebang"

# `--break-system-packages` overrides PEP 668 by doing exactly what it says.
# No installer of ours passes it, whatever the alternative costs. Comments are
# stripped first: the script explains at length why it will not use the flag,
# and naming a thing is not doing it.
sed 's/#.*//' "$SH" | grep -q -- '--break-system-packages'
if [ $? -eq 0 ]; then report 1 "never passes --break-system-packages"; else report 0 "never passes --break-system-packages"; fi

# Hex escapes in printf are a bash extension. On Debian and Ubuntu /bin/sh is
# dash, which prints them literally: the success tick came out as \xe2\x9c\x93.
sed 's/#.*//' "$SH" | grep -q 'printf.*\\x[0-9a-f]'
if [ $? -eq 0 ]; then report 1 "no bash-only \\xNN escapes in printf"; else report 0 "no bash-only \\xNN escapes in printf"; fi

# A tool on PATH is not a tool this machine can run. WSL inherits the Windows
# PATH, so `command -v pipx` answers with a Windows shim on a mounted drive and
# Linux says "Exec format error". `find_tool` returned it without checking, the
# installer chose pipx, and it stopped — on a machine that had uv, venv and pip
# all working.
sed 's/#.*//' "$SH" | grep -q 'runnable() {'
report $? "find_tool verifies that what it found can run"

sed 's/#.*//' "$SH" | grep -q 'remaining_tools'
report $? "a failing install falls through to the next method"

# The behaviour, not just the presence: builds a Windows shim and asks.
sh "$(dirname "$0")/check-lookup.sh" >/dev/null 2>&1
report $? "a Windows shim is refused and a real tool is not"

printf '\ninstall.ps1\n'

# CRLF is correct here; Windows PowerShell wants it.
if od -c "$PS" | grep -q '\\r'; then
    report 0 "has CRLF line endings"
else
    report 1 "has CRLF line endings"
fi

# The ternary operator is PowerShell 7+. Windows PowerShell 5.1 ships with
# Windows and would fail to parse the file at all, so `irm | iex` would print
# nothing but a syntax error.
grep -qE '\)\s*\?\s*.+\s*:\s*' "$PS"
if [ $? -eq 0 ]; then report 1 "no PowerShell 7-only ternary"; else report 0 "no PowerShell 7-only ternary"; fi

if command -v pwsh >/dev/null 2>&1; then
    pwsh -NoProfile -File "$(dirname "$0")/parse-check.ps1" >/dev/null 2>&1
    report $? "parses as PowerShell"
else
    printf '  skip  parses as PowerShell (pwsh not installed)\n'
fi

printf '\n'
if [ "$FAIL" = "0" ]; then
    printf 'all checks passed\n\n'
    exit 0
fi
printf '%s check(s) failed\n\n' "$FAIL"
exit 1
