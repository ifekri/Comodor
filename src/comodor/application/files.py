"""The workspace's files, as a client may browse and read them (D3a).

The desktop window shows the workspace through these methods and nothing else:
it never touches the disk. Every request is a workspace-relative path; the
Core resolves it (symlinks followed) and refuses, before any byte is read,
anything that is outside the workspace, that is Comodor's own data, or that
is likely to hold a secret. These are protocol methods, not agent tools: the
agent cannot call them, and nothing here changes what a mode permits.

What is refused, in the order it is checked (specs/005-workspace-explorer):

1. A path outside the workspace, including through a symlink that escapes it.
2. Comodor's own data, deny-by-default: the whole data folder (the active
   profile's, and the folder that holds every profile) wherever it lies, and
   the project's `.comodor/` except its `skills/`. A workspace that is that
   data folder, or lies inside it, is refused as a whole.
3. A name that usually holds a secret (`.env`, keys, credential files …).
4. Text that contains a known credential shape. This is an aid that lowers
   the chance of a secret reaching the window; it is not a guarantee.

Listing is paged by a keyset cursor, so a folder of any size is read in
pages and no entry is shown twice.
"""

from __future__ import annotations

import base64
import errno
import fnmatch
import hashlib
import json
import os
import stat
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from .. import protocol as P
from ..safety.redact import contains_credential
from ..tools.search import IgnoreRules

#: The largest file the window may open; the same bound the Core's own write
#: and edit tools read whole (`tools/fs.py`).
MAX_OPEN_BYTES = 2_000_000
#: Entries per page of a listing.
PAGE_SIZE = 500
BINARY_SNIFF = 8000
TEXT_ENCODINGS = ("utf-8", "cp1252", "latin-1")

#: Directory names refused wherever they appear (they hold credentials).
SENSITIVE_DIRECTORIES = frozenset({".ssh", ".gnupg", ".aws", ".kube", ".docker"})
#: File names refused wherever they appear (glob patterns, matched on the name).
SENSITIVE_FILES = (
    ".env*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd",
    "credentials", "credentials.*", "secrets.*", "*.secret", "kubeconfig",
    "*.tfvars", "*.tfstate", "*.tfstate.backup",
)
#: Inside the project's `.comodor/`, the only part a client may see.
PROJECT_DATA_ALLOWED = "skills"

#: The reasons a request is refused or a file cannot be shown, as they go on
#: the wire (`error.data.reason`, or `unavailable` on a read).
NOT_FOUND = "not_found"
NOT_A_DIRECTORY = "not_a_directory"
NOT_A_FILE = "not_a_file"
BAD_PATH = "bad_path"
BAD_CURSOR = "bad_cursor"
OUTSIDE_WORKSPACE = "outside_workspace"
COMODOR_DATA = "comodor_data"
WORKSPACE_IS_COMODOR_DATA = "workspace_is_comodor_data"
SENSITIVE_NAME = "sensitive_name"
SECRET_CONTENT = "secret_content"
PERMISSION_DENIED = "permission_denied"
TOO_LARGE = "too_large"
BINARY = "binary"

_CASE_INSENSITIVE = sys.platform in ("win32", "darwin")

#: What a person is told, by reason.
_MESSAGES = {
    WORKSPACE_IS_COMODOR_DATA: "This folder is Comodor's own data folder, so its files are not "
                               "shown here. Open another folder, or point COMODOR_HOME elsewhere.",
    COMODOR_DATA: "This is Comodor's own data, which is not shown here.",
    SENSITIVE_NAME: "This file may contain secrets, so Comodor does not open it here. "
                    "Open it in your own editor.",
    SECRET_CONTENT: "This file appears to contain a secret, so Comodor does not open it here. "
                    "Open it in your own editor.",
}


def _refused(reason: str, message: str) -> P.ProtocolError:
    return P.ProtocolError(P.NOT_ALLOWED, message, {"reason": reason})


def _invalid(reason: str, message: str) -> P.ProtocolError:
    return P.ProtocolError(P.INVALID_PARAMS, message, {"reason": reason})


def _fold(name: str) -> str:
    return name.casefold() if _CASE_INSENSITIVE else name


def _inside(path: Path, root: Path) -> bool:
    """`path` is `root` or below it (both resolved), compared as the platform does."""
    if _CASE_INSENSITIVE:
        p, r = os.path.normcase(str(path)), os.path.normcase(str(root))
        return p == r or p.startswith(r.rstrip("\\/") + os.sep)
    return path == root or root in path.parents


def sensitive_name(name: str, directory: bool) -> bool:
    """Is `name` one that usually holds a secret (4.3)?"""
    folded = _fold(name)
    if directory:
        return folded in {_fold(d) for d in SENSITIVE_DIRECTORIES}
    if folded.endswith(".pub") and not folded.startswith(".env"):
        return False
    return any(fnmatch.fnmatchcase(folded, _fold(pattern)) for pattern in SENSITIVE_FILES)


def _is_link(child: os.DirEntry[str]) -> bool:
    if child.is_symlink():
        return True
    junction = getattr(child, "is_junction", None)
    if junction is not None:
        return junction()
    # Python 3.11 has no DirEntry.is_junction; Windows lstat still exposes
    # the mount-point tag. Other reparse points must not be marked as links.
    mount_point = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
    return mount_point is not None and getattr(
        child.stat(follow_symlinks=False), "st_reparse_tag", None
    ) == mount_point


def line_endings(text: str) -> str:
    """`lf`, `crlf`, `cr`, `mixed` or `none`."""
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    kinds = [kind for kind, count in (("crlf", crlf), ("cr", cr), ("lf", lf)) if count]
    if not kinds:
        return "none"
    return kinds[0] if len(kinds) == 1 else "mixed"


@dataclass(frozen=True)
class Workspace:
    """One workspace and the data folders that must never be shown from it."""

    root: Path
    protected: tuple[Path, ...]

    @classmethod
    def of(cls, project: Path, user: Path) -> "Workspace":
        root = Path(project).resolve()
        data = Path(user).resolve()
        protected = [data]
        # A named profile lives in `<base>/profiles/<name>`: the base holds the
        # default profile's data and every other profile's.
        if data.parent.name == "profiles":
            protected.append(data.parent.parent)
        return cls(root=root, protected=tuple(protected))

    def check_workspace(self) -> None:
        for data in self.protected:
            if _inside(self.root, data):
                raise _refused(WORKSPACE_IS_COMODOR_DATA, _MESSAGES[WORKSPACE_IS_COMODOR_DATA])

    # -- resolving one request --------------------------------------------- #

    def resolve(self, relative: str) -> tuple[Path, str]:
        """The checked absolute path for `relative`, and its normal relative form."""
        self.check_workspace()
        if "\x00" in relative:
            raise _invalid(BAD_PATH, "the path contains a NUL character")
        text = relative.replace("\\", "/").strip("/")
        if text in ("", "."):
            return self.root, ""
        parts = text.split("/")
        if Path(relative).is_absolute() or (len(parts[0]) == 2 and parts[0][1] == ":") \
                or any(part in ("", ".", "..") for part in parts):
            raise _invalid(BAD_PATH, "paths are relative to the workspace, without '.' or '..'")
        candidate = self.root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            raise _refused(OUTSIDE_WORKSPACE, "this path cannot be resolved") from None
        if not _inside(resolved, self.root):
            raise _refused(OUTSIDE_WORKSPACE, "this path is outside the workspace")
        self._check_rules(candidate, resolved)
        return resolved, "/".join(parts)

    def _check_rules(self, candidate: Path, resolved: Path, *, file: bool = False) -> None:
        for data in self.protected:
            if _inside(resolved, data):
                raise _refused(COMODOR_DATA, _MESSAGES[COMODOR_DATA])
        for path in (candidate, resolved):
            try:
                parts = path.relative_to(self.root).parts
            except ValueError:
                parts = ()
            for index, part in enumerate(parts):
                if _fold(part) == _fold(".comodor"):
                    rest = parts[index + 1:]
                    if not rest or _fold(rest[0]) != _fold(PROJECT_DATA_ALLOWED):
                        raise _refused(COMODOR_DATA, _MESSAGES[COMODOR_DATA])
            for index, part in enumerate(parts):
                last = index == len(parts) - 1
                directory = not last or (not file and path.is_dir())
                if sensitive_name(part, directory):
                    raise _refused(SENSITIVE_NAME, _MESSAGES[SENSITIVE_NAME])

    # -- listing -------------------------------------------------------------- #

    def list(self, relative: str = "", cursor: str = "", limit: int = PAGE_SIZE) -> dict[str, Any]:
        directory, normal = self.resolve(relative)
        if not directory.exists():
            raise _invalid(NOT_FOUND, "there is nothing at this path")
        if not directory.is_dir():
            raise _invalid(NOT_A_DIRECTORY, "this is not a folder")
        after = _decode_cursor(cursor, normal) if cursor else None
        limit = max(1, min(int(limit or PAGE_SIZE), PAGE_SIZE))
        rules = IgnoreRules(self.root)
        entries: list[tuple[tuple[int, str, str], dict[str, Any]]] = []
        try:
            children = list(os.scandir(directory))
        except PermissionError:
            raise _refused(PERMISSION_DENIED, "the folder cannot be read") from None
        for child in children:
            entry = self._entry(child, normal, rules)
            if entry is not None:
                is_dir = entry["kind"] == "directory"
                key = (0 if is_dir else 1, child.name.casefold(), child.name)
                if after is None or key > after:
                    entries.append((key, entry))
        entries.sort(key=lambda item: item[0])
        page = entries[:limit]
        result: dict[str, Any] = {"path": normal, "entries": [entry for _, entry in page]}
        if len(entries) > limit:
            result["cursor"] = _encode_cursor(normal, page[-1][0])
        return result

    def _entry(self, child: os.DirEntry[str], parent: str,
               rules: IgnoreRules) -> dict[str, Any] | None:
        path = Path(child.path)
        if rules.ignored(path):
            return None
        relative = f"{parent}/{child.name}" if parent else child.name
        try:
            # A Windows junction is a link too, though `is_symlink` says no.
            is_link = _is_link(child)
            is_dir = child.is_dir(follow_symlinks=True)
        except OSError:
            return None
        entry: dict[str, Any] = {"name": child.name, "path": relative,
                                 "kind": "directory" if is_dir else "file"}
        if is_link:
            entry["link"] = True
        try:
            self._check_rules(path, path.resolve(strict=False))
            if not _inside(path.resolve(strict=False), self.root):
                entry["refused"] = OUTSIDE_WORKSPACE
        except P.ProtocolError as refusal:
            reason = refusal.data.get("reason")
            if reason == COMODOR_DATA:
                return None          # Comodor's data is not listed at all.
            entry["refused"] = reason
        if not is_dir and "refused" not in entry:
            try:
                entry["size"] = child.stat(follow_symlinks=True).st_size
            except OSError:
                pass
        return entry

    # -- one file ------------------------------------------------------------- #

    @contextmanager
    def _open_read(self, path: Path) -> Iterator[BinaryIO]:
        # Resolution alone is not confinement: an ancestor can be exchanged
        # for a link before open. Pin every resolved directory, refusing any
        # new links, and keep the resulting file open through validation/read.
        with ExitStack() as stack:
            if os.name == "nt":
                if path.is_dir():
                    raise _invalid(NOT_A_FILE, "this is a folder")
                fd = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                parent = os.open(path.anchor, flags)
                stack.callback(os.close, parent)
                for part in path.parent.parts[1:]:
                    parent = os.open(part, flags, dir_fd=parent)
                    stack.callback(os.close, parent)
                fd = os.open(path.name or ".", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent)
            # Register ownership before anything else can fail.
            stack.callback(os.close, fd)
            handle = stack.enter_context(os.fdopen(fd, "rb", closefd=False))
            if os.name == "nt":
                # Windows lacks openat/O_NOFOLLOW. Validate the name belonging
                # to the opened handle, never a second resolution of the path.
                actual = _windows_final_path(fd)
                if not _inside(actual, self.root):
                    raise _refused(OUTSIDE_WORKSPACE, "this path is outside the workspace")
                self._check_rules(path, actual, file=True)
            else:
                self._check_rules(path, path, file=True)
            yield handle

    def stat(self, relative: str) -> dict[str, Any]:
        path, normal = self.resolve(relative)
        try:
            info = path.stat()
        except FileNotFoundError:
            raise _invalid(NOT_FOUND, "there is nothing at this path") from None
        except PermissionError:
            raise _refused(PERMISSION_DENIED, "the file cannot be read") from None
        kind = "directory" if path.is_dir() else "file"
        result: dict[str, Any] = {"path": normal, "kind": kind, "modified_ns": info.st_mtime_ns}
        if kind == "file":
            result["size"] = info.st_size
        return result

    def read(self, relative: str) -> dict[str, Any]:
        path, normal = self.resolve(relative)
        try:
            with self._open_read(path) as handle:
                info = os.fstat(handle.fileno())
                # A FIFO, socket or device is never read. O_NONBLOCK also
                # prevents a FIFO installed during open from blocking the Core.
                if not stat.S_ISREG(info.st_mode):
                    raise _invalid(NOT_A_FILE, "this is not a regular file")
                result: dict[str, Any] = {"path": normal, "size": info.st_size}
                if info.st_size > MAX_OPEN_BYTES:
                    return {**result, "unavailable": TOO_LARGE}
                raw = handle.read(MAX_OPEN_BYTES + 1)
        except FileNotFoundError:
            raise _invalid(NOT_FOUND, "there is nothing at this path") from None
        except PermissionError:
            raise _refused(PERMISSION_DENIED, "the file cannot be read") from None
        except IsADirectoryError:
            raise _invalid(NOT_A_FILE, "this is a folder") from None
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise _refused(OUTSIDE_WORKSPACE, "this path changed during access") from None
            if exc.errno in (errno.ENXIO, errno.ENODEV):
                raise _invalid(NOT_A_FILE, "this is not a regular file") from None
            raise _invalid(NOT_FOUND, "the file could not be read") from None
        if len(raw) > MAX_OPEN_BYTES:
            return {**result, "size": len(raw), "unavailable": TOO_LARGE}
        if b"\x00" in raw[:BINARY_SNIFF]:
            return {**result, "unavailable": BINARY}
        bom = raw.startswith(b"\xef\xbb\xbf")
        body = raw[3:] if bom else raw
        text, encoding, replaced = _decode(body, bom)
        # Last, on the decoded text and before anything is returned.
        if contains_credential(text):
            raise _refused(SECRET_CONTENT, _MESSAGES[SECRET_CONTENT])
        return {**result, "text": text, "encoding": encoding, "bom": bom, "replaced": replaced,
                "eol": line_endings(text), "lines": len(text.splitlines()),
                "hash": hashlib.sha256(raw).hexdigest()}


def _windows_final_path(fd: int) -> Path:
    """The final DOS path of this handle, including any traversed junctions."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    final_path = kernel.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD
    handle = msvcrt.get_osfhandle(fd)
    size = final_path(handle, None, 0, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = final_path(handle, buffer, len(buffer), 0)
    if not written or written >= len(buffer):
        raise OSError("the opened file's path could not be verified")
    name = buffer.value
    if name.startswith("\\\\?\\UNC\\"):
        name = "\\\\" + name[8:]
    elif name.startswith("\\\\?\\"):
        name = name[4:]
    return Path(name)


def _decode(body: bytes, bom: bool) -> tuple[str, str, bool]:
    """The text, the encoding it was decoded as, and whether bytes were replaced."""
    for encoding in (("utf-8",) if bom else TEXT_ENCODINGS):
        try:
            return body.decode(encoding), encoding, False
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace"), "utf-8", True


def _encode_cursor(directory: str, key: tuple[int, str, str]) -> str:
    raw = json.dumps({"d": directory, "k": list(key)}, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str, directory: str) -> tuple[int, str, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        kind, folded, name = data["k"]
        if data["d"] != directory or kind not in (0, 1):
            raise ValueError
        return int(kind), str(folded), str(name)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError):
        raise _invalid(BAD_CURSOR, "this cursor does not belong to this folder") from None
