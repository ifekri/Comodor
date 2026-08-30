Add a `--json` flag to `wordcount.py`.

With it, the script prints one JSON object to stdout and nothing else — no
human-readable line alongside it. The object has exactly these keys:

    {"path": "sample.txt", "words": 6, "lines": 4, "characters": 29}

`path` is the name given on the command line, unchanged. The other three come
from `measure`, which already computes them and must not change.

Without the flag the output stays exactly as it is now.

An unreadable file must still print the error to stderr and exit 1, whether or
not `--json` was given; with `--json` nothing is printed to stdout in that case.
