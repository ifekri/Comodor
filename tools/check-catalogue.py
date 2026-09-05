#!/usr/bin/env python3
"""Check that the published catalogue is there and that Comodor can read it.

The local model catalogue is fetched from a branch rather than shipped, so that
adding a model is an edit to a file instead of a release. That is the point of
it, and it is also the failure mode: nothing in the program complains when the
fetch does not work.

It cannot complain. The loader has four rungs —

    1  a cached copy less than a day old
    2  the published catalogue          <- this file checks that one
    3  the cached copy however old
    4  the snapshot bundled in the package

— and falling to the bottom is *correct* behaviour for somebody with no
network. So a URL that 404s and a laptop on a train look identical from inside,
and the catalogue pointed at a file that had never been published for weeks
without anybody noticing.

This is the thing that notices. It is deliberately not a unit test: unit tests
must not need the internet, and a check that is skipped when the network is
absent is a check that reports success on the day it matters.

    python tools/check-catalogue.py              # the published URL
    python tools/check-catalogue.py path/to.json # a file, before publishing it
    python tools/check-catalogue.py --url https://…/branch/local-models.json

Exit status is 0 if the catalogue is usable and 1 if it is not, so CI and a
person get the same answer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from comodor.local.catalogue import (  # noqa: E402  (after sys.path)
    CATALOGUE_URL,
    SCHEMA,
    BadCatalogue,
    parse,
)

#: A checksum is 64 lowercase hex characters or it is not one.
SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: Long enough for a slow runner, short enough that a hang is a failure rather
#: than a job that sits there.
TIMEOUT = 30.0


class Failed(Exception):
    """A check did not pass. The message is the report."""


def fetch(url: str) -> str:
    """The published document, or a failure that says which part broke."""
    request = urllib.request.Request(
        url, headers={"user-agent": "comodor-catalogue-health"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            status = answer.status
            body = answer.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as problem:
        # The case this whole file exists for. Named, rather than folded into
        # "could not fetch", because a 404 means somebody has to publish a file
        # and a 500 means waiting.
        raise Failed(f"HTTP {problem.code} from {url}\n"
                     f"  A 404 here means the catalogue is not published at "
                     f"that location.\n"
                     f"  Every install is silently using the bundled snapshot "
                     f"instead.") from None
    except Exception as problem:
        raise Failed(f"could not reach {url}: {problem}") from None

    if status != 200:
        raise Failed(f"HTTP {status} from {url}")
    return body


def check(body: str, where: str) -> int:
    """Every property a published catalogue has to have. Returns the count."""
    try:
        document = json.loads(body)
    except ValueError as problem:
        raise Failed(f"{where} is not valid JSON: {problem}") from None

    if not isinstance(document, dict):
        raise Failed(f"{where} is not a JSON object")
    if "models" not in document:
        raise Failed(f"{where} has no top-level `models`")
    if not isinstance(document["models"], list):
        raise Failed(f"{where}: `models` is not a list")
    if not document["models"]:
        raise Failed(f"{where}: `models` is empty")

    # The program's own parser, not a second implementation of it. A checker
    # that agreed with itself rather than with the code would pass a document
    # the program refuses.
    try:
        catalogue = parse(body, "live")
    except BadCatalogue as problem:
        raise Failed(f"{where}: Comodor's parser refuses it: {problem}") from None

    stated = len(document["models"])
    kept = len(catalogue.models)
    if kept != stated:
        # Not fatal in the program — one bad entry is skipped so a typo cannot
        # empty the picker — but it is fatal here, because a published entry
        # that nobody can see is a mistake somebody meant to make work.
        raise Failed(f"{where}: {stated - kept} of {stated} entries were "
                     f"dropped by the parser. A published entry that the "
                     f"program silently skips is worse than an absent one.")

    ids = [model.id for model in catalogue.models]
    duplicates = {name for name in ids if ids.count(name) > 1}
    if duplicates:
        raise Failed(f"{where}: duplicate ids {sorted(duplicates)} — the "
                     f"second one is dropped and the file looks fine")

    for model in catalogue.models:
        at = f"{where}: {model.id}"
        if not model.url.startswith("https://"):
            raise Failed(f"{at}: not served over https")
        if not isinstance(model.size, int) or model.size <= 0:
            raise Failed(f"{at}: size is not a positive integer")
        if model.sha256 and not SHA256.match(model.sha256):
            raise Failed(f"{at}: sha256 is not 64 hex characters")

    if catalogue.schema > SCHEMA:
        # Read as far as it can be rather than refused, by design — but worth
        # saying out loud, because it means older installs are seeing less than
        # what is published.
        print(f"  note: schema {catalogue.schema} is newer than the {SCHEMA} "
              f"this checkout understands")

    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?",
                        help="a local file to check instead of the URL")
    parser.add_argument("--url", default=CATALOGUE_URL,
                        help="the catalogue to fetch (default: the published one)")
    given = parser.parse_args()

    where = given.path or given.url
    print(f"Checking {where}")

    try:
        if given.path:
            body = Path(given.path).read_text(encoding="utf-8")
        else:
            body = fetch(given.url)
        count = check(body, where)
    except Failed as problem:
        print(f"\nFAILED\n  {problem}")
        return 1
    except OSError as problem:
        print(f"\nFAILED\n  {problem}")
        return 1

    print(f"  {count} model(s), all usable")
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
