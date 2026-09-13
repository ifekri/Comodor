"""A workspace package's `bin` is a promise npm keeps by editing the file.

`npm ci` links every declared `bin` into `node_modules/.bin` and then, on
Linux and macOS, `chmod`s the target to 0755 (`bin-links/lib/fix-bin.js`).
A target tracked as `100644` is therefore modified by dependency
installation alone — and the release build's integrity guard, which refuses
any change outside the generated TUI artifact, refused the whole release:
`v2.0.0` failed on ` M apps/tui/src/main.tsx` with not one byte changed,
only the mode. Windows never shows it: git ignores the executable bit there.

So the invariant, checked from the index where it is the same on every
platform: a file a workspace declares as a bin is tracked executable. A
package that needs no bin — the interface is started by `bun run` on its
entry, never through npm — declares none.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workspace_packages() -> list[Path]:
    """The root package and every workspace member it names."""
    root = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    found = [ROOT / "package.json"]
    for pattern in root.get("workspaces", []):
        for manifest in sorted(ROOT.glob(f"{pattern}/package.json")):
            found.append(manifest)
    return found


def tracked_mode(path: Path) -> str:
    """The mode git tracks for `path`, e.g. `100644`; empty if untracked."""
    listed = subprocess.run(
        ["git", "ls-files", "--stage", "--", path.relative_to(ROOT).as_posix()],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return listed[0] if listed else ""


def declared_bins() -> list[tuple[Path, str, Path]]:
    bins = []
    for manifest in workspace_packages():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        declared = data.get("bin")
        if isinstance(declared, str):
            declared = {data.get("name", manifest.parent.name): declared}
        for name, target in (declared or {}).items():
            bins.append((manifest, name, (manifest.parent / target).resolve()))
    return bins


def test_every_declared_bin_is_tracked_executable():
    wrong = []
    for manifest, name, target in declared_bins():
        mode = tracked_mode(target)
        if mode != "100755":
            wrong.append(f"{manifest.relative_to(ROOT).as_posix()} bin {name!r} -> "
                         f"{target.relative_to(ROOT).as_posix()} is tracked as "
                         f"{mode or 'untracked'}, and `npm ci` will chmod it to 0755")
    assert not wrong, "\n".join(wrong)


def test_the_interface_entry_is_source_not_an_npm_bin():
    """`apps/tui/src/main.tsx` is bundled by `bun build` and run by `bun run`;
    nothing invokes it through `node_modules/.bin`. Declaring it as a bin
    made npm rewrite its mode on every install, which is what broke the
    v2.0.0 release build."""
    manifest = json.loads((ROOT / "apps" / "tui" / "package.json").read_text(encoding="utf-8"))
    assert "bin" not in manifest, manifest["bin"]
    assert tracked_mode(ROOT / "apps" / "tui" / "src" / "main.tsx") == "100644"
