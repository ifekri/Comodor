"""The workspace as the desktop window browses and reads it (D3a).

Every rule that keeps a file out of the window is tested on its own, through
the same `Workspace` the protocol methods use, and the protocol seam is
crossed once for each kind of answer.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

from comodor import protocol as P
from comodor.application import CoreService
from comodor.application import files as F
from comodor.application.files import Workspace
from comodor.config import Config
from comodor.paths import Paths
from comodor.transport.jsonl import Channel
from comodor.transport.server import Server


def reason(problem: pytest.ExceptionInfo[P.ProtocolError]) -> str:
    return problem.value.data.get("reason", "")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def ws(workspace: Path, home: Path) -> Workspace:
    return Workspace.of(workspace, home)


def can_symlink(tmp_path: Path) -> bool:
    try:
        (tmp_path / "probe-link").symlink_to(tmp_path)
        (tmp_path / "probe-link").unlink()
        return True
    except (OSError, NotImplementedError):
        return False


# --------------------------------------------------------------------------- #
# listing
# --------------------------------------------------------------------------- #


def test_folders_come_first_then_names_without_regard_to_case(workspace: Path, ws: Workspace):
    for name in ("b.txt", "A.txt", "c.txt"):
        (workspace / name).write_bytes("x".encode("utf-8"))
    (workspace / "zdir").mkdir()
    names = [e["name"] for e in ws.list("")["entries"]]
    assert names[:2] == ["src", "zdir"]
    assert names[2:] == ["A.txt", "b.txt", "c.txt", "pyproject.toml"]


def test_a_large_folder_is_paged_and_every_entry_appears_exactly_once(workspace: Path,
                                                                       ws: Workspace):
    big = workspace / "big"
    big.mkdir()
    for index in range(1201):
        (big / f"f{index:05d}.txt").write_bytes("".encode("utf-8"))
    seen: list[str] = []
    page = ws.list("big")
    pages = 1
    for _ in range(10):   # a bound: a cursor that never advances fails, it does not loop
        seen += [e["name"] for e in page["entries"]]
        assert len(page["entries"]) <= F.PAGE_SIZE
        if "cursor" not in page:
            break
        page = ws.list("big", page["cursor"])
        pages += 1
    assert pages == 3
    assert len(seen) == 1201 == len(set(seen))


def test_entries_added_between_pages_are_never_listed_twice(workspace: Path, ws: Workspace):
    folder = workspace / "grow"
    folder.mkdir()
    for index in range(20):
        (folder / f"m{index:02d}").write_bytes("".encode("utf-8"))
    first = ws.list("grow", limit=10)
    (folder / "a-before").write_bytes("".encode("utf-8"))   # sorts before the cursor
    (folder / "z-after").write_bytes("".encode("utf-8"))    # sorts after it
    rest = ws.list("grow", first["cursor"], limit=500)
    names = [e["name"] for e in first["entries"] + rest["entries"]]
    assert len(names) == len(set(names))
    assert "z-after" in names and "a-before" not in names


def test_a_cursor_only_continues_the_folder_it_came_from(workspace: Path, ws: Workspace):
    for index in range(3):
        (workspace / "src" / f"{index}.py").write_bytes("".encode("utf-8"))
    cursor = ws.list("src", limit=1)["cursor"]
    with pytest.raises(P.ProtocolError) as wrong:
        ws.list("", cursor)
    assert reason(wrong) == F.BAD_CURSOR
    with pytest.raises(P.ProtocolError) as garbage:
        ws.list("src", "not-a-cursor")
    assert reason(garbage) == F.BAD_CURSOR


def test_ignored_entries_are_not_listed(workspace: Path, ws: Workspace):
    (workspace / ".gitignore").write_bytes("*.log\nbuild-out/\n".encode("utf-8"))
    (workspace / "app.log").write_bytes("".encode("utf-8"))
    (workspace / "build-out").mkdir()
    (workspace / "node_modules").mkdir()
    (workspace / ".git").mkdir()
    names = {e["name"] for e in ws.list("")["entries"]}
    assert not names & {"app.log", "build-out", "node_modules", ".git"}


def test_listing_a_file_or_a_missing_folder_says_so(workspace: Path, ws: Workspace):
    with pytest.raises(P.ProtocolError) as missing:
        ws.list("nope")
    assert reason(missing) == F.NOT_FOUND
    with pytest.raises(P.ProtocolError) as file:
        ws.list("pyproject.toml")
    assert reason(file) == F.NOT_A_DIRECTORY


# --------------------------------------------------------------------------- #
# confinement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["..", "../outside.txt", "src/../../outside.txt", "./src",
                                  "C:/Windows/win.ini", "src/./x"])
def test_dot_segments_and_drive_paths_are_refused(ws: Workspace, path: str):
    with pytest.raises(P.ProtocolError) as refused:
        ws.read(path)
    assert reason(refused) == F.BAD_PATH


def test_an_absolute_path_is_refused(tmp_path: Path, ws: Workspace):
    outside = tmp_path / "outside.txt"
    outside.write_bytes("secret-ish".encode("utf-8"))
    with pytest.raises(P.ProtocolError) as refused:
        ws.read(str(outside))
    assert reason(refused) == F.BAD_PATH


def test_a_symlink_that_escapes_the_workspace_is_listed_but_never_followed(
        tmp_path: Path, workspace: Path, ws: Workspace):
    if not can_symlink(tmp_path):
        pytest.skip("this machine cannot create symlinks")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "notes.txt").write_bytes("outside".encode("utf-8"))
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    entry = next(e for e in ws.list("")["entries"] if e["name"] == "escape")
    assert entry["refused"] == F.OUTSIDE_WORKSPACE and entry["link"] is True
    for call in (lambda: ws.list("escape"), lambda: ws.read("escape/notes.txt")):
        with pytest.raises(P.ProtocolError) as refused:
            call()
        assert reason(refused) == F.OUTSIDE_WORKSPACE


def link_outside(link: Path, target: Path) -> bool:
    """A link `link` -> `target`: a symlink, or on Windows a directory junction
    (which needs no privilege), so confinement is tested on every platform."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return True
    return False


def test_a_link_that_resolves_outside_is_refused_on_every_platform(tmp_path: Path, workspace: Path,
                                                                    ws: Workspace):
    outside = tmp_path / "beyond"
    outside.mkdir()
    (outside / "notes.txt").write_bytes(b"outside")
    if not link_outside(workspace / "door", outside):
        pytest.skip("this machine can create neither a symlink nor a junction")
    entry = next(e for e in ws.list()["entries"] if e["name"] == "door")
    assert entry["refused"] == F.OUTSIDE_WORKSPACE
    for call in (lambda: ws.list("door"), lambda: ws.read("door/notes.txt"),
                 lambda: ws.stat("door")):
        with pytest.raises(P.ProtocolError) as refused:
            call()
        assert reason(refused) == F.OUTSIDE_WORKSPACE


def test_an_outside_resolved_directory_is_locked_even_without_a_symlink_flag(
        tmp_path: Path, workspace: Path, ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    # A Windows junction resolves elsewhere but DirEntry.is_symlink() is false.
    # Model that resolution on every platform so the listing policy is exercised.
    door = workspace / "door"
    door.mkdir()
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        return tmp_path if path == door else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    entry = next(e for e in ws.list()["entries"] if e["name"] == "door")
    assert entry["kind"] == "directory"
    assert entry["refused"] == F.OUTSIDE_WORKSPACE


def test_an_oversized_file_is_never_read_into_memory(workspace: Path, ws: Workspace,
                                                     monkeypatch: pytest.MonkeyPatch):
    with (workspace / "huge.log").open("wb") as handle:
        handle.truncate(F.MAX_OPEN_BYTES + 10)
    reads: list[Path] = []
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (reads.append(self), original(self))[1])
    assert ws.read("huge.log")["unavailable"] == F.TOO_LARGE
    assert reads == []


def test_a_symlink_inside_the_workspace_is_followed(tmp_path: Path, workspace: Path, ws: Workspace):
    if not can_symlink(tmp_path):
        pytest.skip("this machine cannot create symlinks")
    (workspace / "src" / "a.py").write_bytes("print(1)\n".encode("utf-8"))
    (workspace / "alias").symlink_to(workspace / "src", target_is_directory=True)
    assert ws.read("alias/a.py")["text"] == "print(1)\n"


# --------------------------------------------------------------------------- #
# Comodor's own data
# --------------------------------------------------------------------------- #


def test_the_data_folder_inside_the_workspace_is_hidden_and_refused(tmp_path: Path):
    """The common case of a workspace at the home folder (~/.comodor inside it)."""
    homefolder = tmp_path / "me"
    data = homefolder / ".comodor-data"
    (data / "github").mkdir(parents=True)
    (data / "config.json").write_bytes('{"providers": {}}'.encode("utf-8"))
    (homefolder / "notes.txt").write_bytes("hello".encode("utf-8"))
    ws = Workspace.of(homefolder, data)
    names = {e["name"] for e in ws.list("")["entries"]}
    assert "notes.txt" in names and ".comodor-data" not in names
    for path in (".comodor-data/config.json", ".comodor-data/github", ".comodor-data/new-file.txt"):
        with pytest.raises(P.ProtocolError) as refused:
            ws.read(path)
        assert reason(refused) == F.COMODOR_DATA
    assert ws.read("notes.txt")["text"] == "hello"


@pytest.mark.parametrize("where", ["same", "inside"])
def test_a_workspace_that_is_or_lies_in_the_data_folder_is_refused_whole(tmp_path: Path,
                                                                         where: str):
    data = tmp_path / "comodor-home"
    (data / "project").mkdir(parents=True)
    (data / "config.json").write_bytes("{}".encode("utf-8"))
    ws = Workspace.of(data if where == "same" else data / "project", data)
    for call in (lambda: ws.list(""), lambda: ws.read("config.json"), lambda: ws.stat("")):
        with pytest.raises(P.ProtocolError) as refused:
            call()
        assert reason(refused) == F.WORKSPACE_IS_COMODOR_DATA
    # A file Comodor writes there later is refused the same way: nothing is
    # decided by name.
    (data / "a-new-store.db").write_bytes("".encode("utf-8"))
    with pytest.raises(P.ProtocolError) as later:
        ws.read("a-new-store.db")
    assert reason(later) == F.WORKSPACE_IS_COMODOR_DATA


def test_a_named_profile_protects_the_folder_that_holds_every_profile(tmp_path: Path):
    base = tmp_path / "me" / ".comodor"
    profile = base / "profiles" / "work"
    profile.mkdir(parents=True)
    (base / "config.json").write_bytes("{}".encode("utf-8"))
    ws = Workspace.of(tmp_path / "me", profile)
    with pytest.raises(P.ProtocolError) as refused:
        ws.read(".comodor/config.json")
    assert reason(refused) == F.COMODOR_DATA


def test_the_projects_comodor_folder_is_refused_except_its_skills(workspace: Path, ws: Workspace):
    project = workspace / ".comodor"
    (project / "checkpoints").mkdir(parents=True)
    (project / "skills").mkdir()
    (project / "checkpoints" / "old.bin").write_bytes("earlier bytes".encode("utf-8"))
    (project / "config.json").write_bytes("{}".encode("utf-8"))
    (project / "anything-new").write_bytes("".encode("utf-8"))
    (project / "skills" / "deploy.md").write_bytes("# deploy\n".encode("utf-8"))
    for method, path in ((ws.list, ".comodor"), (ws.list, ".comodor/checkpoints"),
                         (ws.read, ".comodor/checkpoints/old.bin"),
                         (ws.read, ".comodor/config.json"), (ws.read, ".comodor/anything-new")):
        with pytest.raises(P.ProtocolError) as refused:
            method(path)
        assert reason(refused) == F.COMODOR_DATA, path
    assert ws.read(".comodor/skills/deploy.md")["text"] == "# deploy\n"


# --------------------------------------------------------------------------- #
# secrets
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", [".env", ".env.local", "server.pem", "tls.key", "id_rsa",
                                  "id_ed25519",
                                  ".npmrc", ".netrc", "credentials", "credentials.json",
                                  "secrets.yaml", "prod.tfvars", "terraform.tfstate", "kubeconfig"])
def test_names_that_usually_hold_secrets_are_listed_locked_and_never_read(
        workspace: Path, ws: Workspace, name: str):
    (workspace / name).write_bytes("value".encode("utf-8"))
    entry = next(e for e in ws.list("")["entries"] if e["name"] == name)
    assert entry["refused"] == F.SENSITIVE_NAME and "size" not in entry
    with pytest.raises(P.ProtocolError) as refused:
        ws.read(name)
    assert reason(refused) == F.SENSITIVE_NAME


def test_a_public_key_and_an_ordinary_name_are_not_refused(workspace: Path, ws: Workspace):
    (workspace / "id_rsa.pub").write_bytes("ssh-rsa AAAA".encode("utf-8"))
    (workspace / "environment.md").write_bytes("notes".encode("utf-8"))
    assert ws.read("id_rsa.pub")["text"] == "ssh-rsa AAAA"
    assert ws.read("environment.md")["text"] == "notes"


def test_a_folder_that_holds_keys_is_refused_with_everything_in_it(workspace: Path, ws: Workspace):
    (workspace / ".ssh").mkdir()
    (workspace / ".ssh" / "config").write_bytes("Host x".encode("utf-8"))
    with pytest.raises(P.ProtocolError) as refused:
        ws.read(".ssh/config")
    assert reason(refused) == F.SENSITIVE_NAME


@pytest.mark.parametrize("token", [
    "ghp_" + "a1B2c3D4" * 4,
    "eyJ" + "A" * 5000 + "." + "B" * 5000 + "." + "C" * 5000,
    "-----BEGIN RSA PRIVATE KEY-----" + "X" * 20000 + "-----END RSA PRIVATE KEY-----",
])
def test_a_credential_shape_in_an_ordinary_file_is_refused_before_it_is_returned(
        workspace: Path, ws: Workspace, token: str):
    (workspace / "src" / "client.ts").write_bytes(f'const token = "{token}";\n'.encode("utf-8"))
    with pytest.raises(P.ProtocolError) as refused:
        ws.read("src/client.ts")
    assert reason(refused) == F.SECRET_CONTENT
    assert token not in str(refused.value.envelope("x"))


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw,encoding,bom,eol,lines", [
    (b"a\nb\n", "utf-8", False, "lf", 2),
    (b"a\r\nb\r\n", "utf-8", False, "crlf", 2),
    (b"a\rb\r", "utf-8", False, "cr", 2),
    (b"a\r\nb\nc", "utf-8", False, "mixed", 3),
    (b"single line", "utf-8", False, "none", 1),
    (b"\xef\xbb\xbfa\nb\n", "utf-8", True, "lf", 2),
    ("caf\u00e9 \u2013 \u20ac\n".encode("cp1252"), "cp1252", False, "lf", 1),
    ("\u0633\u0644\u0627\u0645 \U0001F600 e\u0301\n".encode("utf-8"), "utf-8", False, "lf", 1),
])
def test_a_text_file_comes_back_with_how_it_was_decoded(workspace: Path, ws: Workspace, raw: bytes,
                                                        encoding: str, bom: bool, eol: str,
                                                        lines: int):
    (workspace / "f.txt").write_bytes(raw)
    got = ws.read("f.txt")
    assert (got["encoding"], got["bom"], got["eol"], got["lines"]) == (encoding, bom, eol, lines)
    assert got["hash"] == hashlib.sha256(raw).hexdigest()
    assert got["size"] == len(raw)
    assert not got["text"].startswith("\ufeff")


def test_a_binary_or_oversized_file_is_unavailable_and_sends_no_text(workspace: Path,
                                                                     ws: Workspace):
    (workspace / "image.bin").write_bytes(b"PK\x00\x03" + bytes(100))
    with (workspace / "huge.txt").open("wb") as handle:
        handle.truncate(F.MAX_OPEN_BYTES + 1)
    binary, huge = ws.read("image.bin"), ws.read("huge.txt")
    assert binary["unavailable"] == F.BINARY and "text" not in binary
    assert huge["unavailable"] == F.TOO_LARGE and "text" not in huge
    assert huge["size"] == F.MAX_OPEN_BYTES + 1


def test_a_file_at_the_limit_opens(workspace: Path, ws: Workspace):
    (workspace / "edge.txt").write_bytes(b"a" * F.MAX_OPEN_BYTES)
    assert len(ws.read("edge.txt")["text"]) == F.MAX_OPEN_BYTES


def test_stat_reports_kind_size_and_time(workspace: Path, ws: Workspace):
    (workspace / "f.txt").write_bytes(b"12345")
    assert ws.stat("f.txt")["size"] == 5 and ws.stat("f.txt")["kind"] == "file"
    assert ws.stat("src")["kind"] == "directory" and "size" not in ws.stat("src")
    with pytest.raises(P.ProtocolError) as missing:
        ws.stat("gone.txt")
    assert reason(missing) == F.NOT_FOUND


def test_reading_a_folder_is_not_a_read(ws: Workspace):
    with pytest.raises(P.ProtocolError) as refused:
        ws.read("src")
    assert reason(refused) == F.NOT_A_FILE


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_a_fifo_is_rejected_before_opening_it(
        workspace: Path, ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    os.mkfifo(workspace / "pipe")

    def unexpected_read(path):
        pytest.fail("a FIFO must be refused before a read can block the Core")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    with pytest.raises(P.ProtocolError) as refused:
        ws.read("pipe")
    assert refused.value.code == P.INVALID_PARAMS
    assert reason(refused) == F.NOT_A_FILE


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_an_unreadable_file_says_so(workspace: Path, ws: Workspace):
    target = workspace / "locked.txt"
    target.write_bytes("x".encode("utf-8"))
    target.chmod(0)
    try:
        if os.access(target, os.R_OK):
            pytest.skip("running with privileges that ignore file modes")
        with pytest.raises(P.ProtocolError) as refused:
            ws.read("locked.txt")
        assert reason(refused) == F.PERMISSION_DENIED
    finally:
        target.chmod(0o600)


# --------------------------------------------------------------------------- #
# the protocol seam
# --------------------------------------------------------------------------- #


def serve(service: CoreService, *requests: dict) -> list[dict]:
    lines = [{"version": P.PROTOCOL_VERSION, "type": "request", "id": "h", "method": "client.hello",
              "params": {"protocol_version": P.PROTOCOL_VERSION,
                         "client": {"name": "test", "version": "0"}}}, *requests]
    out = io.StringIO()
    channel = Channel(reader=io.StringIO("\n".join(json.dumps(r) for r in lines) + "\n"),
                      writer=out, log=io.StringIO())
    Server(service, channel).serve()
    return [json.loads(row) for row in out.getvalue().splitlines()]


def call(id: str, method: str, params: dict) -> dict:
    return {"version": P.PROTOCOL_VERSION, "type": "request", "id": id, "method": method,
            "params": params}


def test_the_methods_cross_the_protocol_with_their_reasons(config: Config, workspace: Path):
    (workspace / "src" / "app.py").write_bytes("print('hi')\n".encode("utf-8"))
    (workspace / ".env").write_bytes("A=1".encode("utf-8"))
    service = CoreService(config)
    try:
        answers = {a.get("id"): a for a in serve(
            service,
            call("l", "workspace.list", {"path": "src"}),
            call("r", "workspace.read", {"path": "src/app.py"}),
            call("s", "workspace.stat", {"path": "src/app.py"}),
            call("e", "workspace.read", {"path": ".env"}),
            call("o", "workspace.read", {"path": "../x"}),
            call("p", "workspace.read", {}),
        )}
    finally:
        service.close()
    assert "workspace_files" in answers["h"]["result"]["capabilities"]
    assert [e["name"] for e in answers["l"]["result"]["entries"]] == ["app.py"]
    assert answers["r"]["result"]["text"] == "print('hi')\n"
    assert answers["s"]["result"]["kind"] == "file"
    assert answers["e"]["error"]["code"] == P.NOT_ALLOWED
    assert answers["e"]["error"]["data"]["reason"] == F.SENSITIVE_NAME
    assert answers["o"]["error"]["data"]["reason"] == F.BAD_PATH
    assert answers["p"]["error"]["code"] == P.INVALID_PARAMS


def test_the_methods_are_not_agent_tools_in_any_mode(config: Config):
    """A person's browsing never becomes something the agent can call, and
    never changes the session's mode."""
    from comodor.safety.modes import ALL as MODES
    from comodor.tools.registry import ToolRegistry

    registry = ToolRegistry(config=config)
    try:
        names = {tool.name for tool in registry.all()}
        names |= {tool.name for mode in MODES for tool in registry.for_mode(mode)}
    finally:
        registry.close()
    assert names, "the registry offered no tools at all: the check below would prove nothing"
    service = CoreService(config)
    try:
        for mode in MODES:
            session = service.create_session(mode=mode)
            assert session["mode"] == mode
            service.workspace_files().list("")
            assert service.get_session(session["id"])["mode"] == mode
    finally:
        service.close()
    assert not {n for n in names if n.startswith("workspace")}


def test_the_workspace_is_the_one_the_core_reports(config: Config, workspace: Path):
    service = CoreService(config)
    try:
        assert Path(service.workspace()["path"]).resolve() == service.workspace_files().root
    finally:
        service.close()


def test_paths_are_built_from_the_configured_data_folder(tmp_path: Path, workspace: Path):
    cfg = Config(paths=Paths(user=workspace / ".comodor-home", project=workspace))
    (workspace / ".comodor-home").mkdir()
    service = CoreService(cfg)
    try:
        names = {e["name"] for e in service.workspace_files().list("")["entries"]}
    finally:
        service.close()
    assert ".comodor-home" not in names
