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

The checks above are made on a resolved path, and the disk can change between
the check and the open: a folder exchanged for a link, a file for a link, a
pipe or a device, a file that grows. So nothing is read by path. What is
opened is proven to be what was checked (`_open`):

- POSIX: every folder below the workspace root is opened one name at a time
  from the folder above it, never following a link (`openat`, `O_NOFOLLOW`);
  the last name is examined without following it, opened the same way and
  without blocking, and must still be the same file (device and inode).
- Windows, which has no `openat`: the path is opened and the opened handle's
  own final path must equal the checked path, so a junction or symlink
  exchanged in anywhere along it is refused. A folder is then listed from
  that handle, not from its path again.
- A system that offers neither is refused whole (`cannot_confine`).

A file is read through the descriptor that was proven, at most one byte past
the limit, so a file that grows is reported too large, never read whole. A
file renamed or hard-linked into the workspace is workspace content: only
the credential scan stands between it and the window.
"""

from __future__ import annotations

import base64
import errno
import fnmatch
import functools
import hashlib
import json
import os
import stat
import struct
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
CHANGED = "changed"
CANNOT_CONFINE = "cannot_confine"

_CASE_INSENSITIVE = sys.platform in ("win32", "darwin")
_WINDOWS = os.name == "nt"
#: Names Windows opens as devices wherever they appear; opening one can block.
_WINDOWS_DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                              *(f"{port}{n}" for port in ("COM", "LPT") for n in "0123456789¹²³")})

#: What a person is told, by reason.
_MESSAGES = {
    WORKSPACE_IS_COMODOR_DATA: "This folder is Comodor's own data folder, so its files are not "
                               "shown here. Open another folder, or point COMODOR_HOME elsewhere.",
    COMODOR_DATA: "This is Comodor's own data, which is not shown here.",
    SENSITIVE_NAME: "This file may contain secrets, so Comodor does not open it here. "
                    "Open it in your own editor.",
    SECRET_CONTENT: "This file appears to contain a secret, so Comodor does not open it here. "
                    "Open it in your own editor.",
    CHANGED: "This path changed while it was being opened, so nothing was shown. "
             "Refresh and try again.",
    CANNOT_CONFINE: "This system cannot open files without the risk of following a path that "
                    "changed underneath, so Comodor does not show the workspace's files here.",
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
    # A public key is not a secret; an env file is, whatever it ends with.
    if folded.endswith(".pub") and not folded.startswith(".env"):
        return False
    return any(fnmatch.fnmatchcase(folded, _fold(pattern)) for pattern in SENSITIVE_FILES)


def _device_name(name: str) -> bool:
    return name.split(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICES


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
        # On Windows `name:stream` opens a file's alternate stream under a
        # name no rule knows, and `COM1` or `CON` opens a device.
        if _WINDOWS and any(":" in part or _device_name(part) for part in parts):
            raise _invalid(BAD_PATH, "this name is a Windows device or stream, not a file")
        candidate = self.root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            raise _refused(OUTSIDE_WORKSPACE, "this path cannot be resolved") from None
        if not _inside(resolved, self.root):
            raise _refused(OUTSIDE_WORKSPACE, "this path is outside the workspace")
        self._check_rules(candidate, resolved)
        return resolved, "/".join(parts)

    def _check_rules(self, candidate: Path, resolved: Path) -> None:
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
                directory = not last or path.is_dir()
                if sensitive_name(part, directory):
                    raise _refused(SENSITIVE_NAME, _MESSAGES[SENSITIVE_NAME])

    # -- opening what was checked, and nothing else ------------------------- #

    @contextmanager
    def _open(self, path: Path, want: str) -> Iterator[tuple[int, os.stat_result]]:
        """A descriptor of the checked, resolved `path` and its status, proven
        to be that path (see the module's docstring). `want` is `file`,
        `directory` or `any` (either); anything else there is refused."""
        if not _confinable():
            raise _refused(CANNOT_CONFINE, _MESSAGES[CANNOT_CONFINE])
        try:
            fd, info = (_open_windows(path) if _WINDOWS else self._open_posix(path))
        except FileNotFoundError:
            raise _invalid(NOT_FOUND, "there is nothing at this path") from None
        except PermissionError:
            raise _refused(PERMISSION_DENIED, "this cannot be read") from None
        except OSError as problem:
            if problem.errno == errno.ELOOP:
                raise _refused(CHANGED, _MESSAGES[CHANGED]) from None
            if problem.errno == errno.ENOTDIR:
                raise _invalid(NOT_FOUND, "there is nothing at this path") from None
            raise _invalid(NOT_FOUND, "this could not be opened") from None
        try:
            is_dir, is_file = stat.S_ISDIR(info.st_mode), stat.S_ISREG(info.st_mode)
            if want == "directory" and not is_dir:
                raise _invalid(NOT_A_DIRECTORY, "this is not a folder")
            if want == "file" and is_dir:
                raise _invalid(NOT_A_FILE, "this is a folder")
            # A FIFO, socket or device is never read: reading one can block the Core.
            if not (is_dir or is_file):
                raise _invalid(NOT_A_FILE, "this is not a regular file")
            yield fd, info
        finally:
            os.close(fd)

    def _open_posix(self, path: Path) -> tuple[int, os.stat_result]:
        names = path.parts[len(self.root.parts):]
        here = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for name in names[:-1]:
                try:
                    below = os.open(name, _POSIX_FOLDER, dir_fd=here)
                except OSError:
                    # Some filesystems say ENOENT or ENOTDIR for a link here.
                    if stat.S_ISLNK(os.stat(name, dir_fd=here, follow_symlinks=False).st_mode):
                        raise OSError(errno.ELOOP, "a link took a folder's place") from None
                    raise
                os.close(here)
                here = below
            if not names:
                info = os.fstat(here)
                opened, here = here, -1
                return opened, info
            last = names[-1]
            before = os.stat(last, dir_fd=here, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise OSError(errno.ELOOP, "a link appeared where the path was checked")
            # A FIFO, socket or device is not even opened.
            if not (stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode)):
                raise _invalid(NOT_A_FILE, "this is not a regular file")
            opened = os.open(last, _POSIX_FOLDER if stat.S_ISDIR(before.st_mode) else _POSIX_FILE,
                             dir_fd=here)
            info = os.fstat(opened)
            if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
                os.close(opened)
                raise OSError(errno.ELOOP, "another file took this path's place")
            return opened, info
        finally:
            if here >= 0:
                os.close(here)

    # -- listing -------------------------------------------------------------- #

    def list(self, relative: str = "", cursor: str = "", limit: int = PAGE_SIZE) -> dict[str, Any]:
        directory, normal = self.resolve(relative)
        after = _decode_cursor(cursor, normal) if cursor else None
        limit = max(1, min(int(limit or PAGE_SIZE), PAGE_SIZE))
        rules = IgnoreRules(self.root)
        entries: list[tuple[tuple[int, str, str], dict[str, Any]]] = []
        with self._open(directory, "directory") as (fd, _):
            try:
                children = _children(fd)
            except PermissionError:
                raise _refused(PERMISSION_DENIED, "the folder cannot be read") from None
            except OSError:
                raise _invalid(NOT_FOUND, "the folder could not be read") from None
        for child in children:
            entry = self._entry(child, directory, normal, rules)
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

    def _entry(self, child: _Child, directory: Path, parent: str,
               rules: IgnoreRules) -> dict[str, Any] | None:
        # What the entry says is only a label: whatever it names is opened,
        # and proven, when it is listed or read itself.
        path = directory / child.name
        if rules.ignored(path):
            return None
        relative = f"{parent}/{child.name}" if parent else child.name
        entry: dict[str, Any] = {"name": child.name, "path": relative,
                                 "kind": "directory" if child.directory else "file"}
        if child.link:
            entry["link"] = True
        try:
            resolved = path.resolve(strict=False)
            self._check_rules(path, resolved)
            if not _inside(resolved, self.root):
                entry["refused"] = OUTSIDE_WORKSPACE
        except P.ProtocolError as refusal:
            reason = refusal.data.get("reason")
            if reason == COMODOR_DATA:
                return None          # Comodor's data is not listed at all.
            entry["refused"] = reason
        except (OSError, RuntimeError):
            entry["refused"] = OUTSIDE_WORKSPACE
        # A link's size would be its target's, read by path: it is left out.
        if not child.directory and not child.link and "refused" not in entry \
                and child.size is not None:
            entry["size"] = child.size
        return entry

    # -- one file ------------------------------------------------------------- #

    def stat(self, relative: str) -> dict[str, Any]:
        path, normal = self.resolve(relative)
        with self._open(path, "any") as (_, info):
            kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
        result: dict[str, Any] = {"path": normal, "kind": kind, "modified_ns": info.st_mtime_ns}
        if kind == "file":
            result["size"] = info.st_size
        return result

    def read(self, relative: str) -> dict[str, Any]:
        path, normal = self.resolve(relative)
        with self._open(path, "file") as (fd, info):
            result: dict[str, Any] = {"path": normal, "size": info.st_size}
            if info.st_size > MAX_OPEN_BYTES:
                return {**result, "unavailable": TOO_LARGE}
            try:
                # One byte past the limit: a file that grew since is too large.
                raw = _read_at_most(fd, MAX_OPEN_BYTES + 1)
            except PermissionError:
                raise _refused(PERMISSION_DENIED, "the file cannot be read") from None
            except OSError:
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


# -- opening, by platform ------------------------------------------------------ #

_POSIX_FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
#: Never blocks on a FIFO or a terminal that took a checked file's place.
_POSIX_FILE = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
               | getattr(os, "O_NOCTTY", 0))


#: Can this system open a path so that what was checked is what is read?
_CONFINABLE = _WINDOWS or (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
                           and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
                           and os.scandir in os.supports_fd)


def _confinable() -> bool:
    return _CONFINABLE


@dataclass(frozen=True)
class _Child:
    """One name in a listed folder, as the folder itself reports it."""

    name: str
    link: bool                  # a symlink, or a Windows junction
    directory: bool
    size: int | None            # a file's own size; None for a link


def _children(fd: int) -> list[_Child]:
    """The names in the folder open as `fd`, read from it rather than from a path."""
    if _WINDOWS:
        return _windows_children(fd)
    children = []
    with os.scandir(fd) as names:
        for child in names:
            try:
                link = child.is_symlink()
                directory = child.is_dir(follow_symlinks=True)
                size = None if directory or link else child.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            children.append(_Child(child.name, link, directory, size))
    return children


def _read_at_most(fd: int, limit: int) -> bytes:
    parts: list[bytes] = []
    left = limit
    while left > 0:
        chunk = os.read(fd, min(left, 1 << 16))
        if not chunk:
            break
        parts.append(chunk)
        left -= len(chunk)
    return b"".join(parts)


_GENERIC_READ = 0x80000000
_SHARE_ALL = 0x1 | 0x2 | 0x4            # read, write, delete: an editor may save meanwhile
_OPEN_EXISTING = 3
_BACKUP_SEMANTICS = 0x02000000          # lets a folder be opened as a handle
_FULL_DIRECTORY_INFO, _FULL_DIRECTORY_RESTART = 14, 15
_NO_MORE_FILES = 18
_ATTRIBUTE_DIRECTORY, _ATTRIBUTE_REPARSE_POINT = 0x10, 0x400
_TAG_SYMLINK, _TAG_MOUNT_POINT = 0xA000000C, 0xA0000003
#: FILE_FULL_DIR_INFO up to its name; with a reparse point, `EaSize` holds the tag (MS-FSCC 2.4.17).
_FULL_DIR_INFO = struct.Struct("<IIqqqqqqIII")


@functools.cache
def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, wintypes.DWORD,
                                                 wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                    wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    return kernel


def _open_windows(path: Path) -> tuple[int, os.stat_result]:
    import ctypes
    import msvcrt

    kernel = _kernel32()
    handle = kernel.CreateFileW(str(path), _GENERIC_READ, _SHARE_ALL, None, _OPEN_EXISTING,
                                _BACKUP_SEMANTICS, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError:
        kernel.CloseHandle(handle)
        raise
    try:
        # The handle says where it really is, junctions and links traversed.
        if os.path.normcase(_final_path(handle)) != os.path.normcase(str(path)):
            raise OSError(errno.ELOOP, "the opened path is not the checked one")
        return fd, os.fstat(fd)
    except BaseException:
        os.close(fd)
        raise


def _final_path(handle: int) -> str:
    import ctypes

    kernel = _kernel32()
    size = kernel.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if size:
        buffer = ctypes.create_unicode_buffer(size + 1)
        written = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if 0 < written < len(buffer):
            name = buffer.value
            if name.startswith("\\\\?\\UNC\\"):
                return "\\\\" + name[8:]
            return name[4:] if name.startswith("\\\\?\\") else name
    # Without the handle's own path, what was opened cannot be proven.
    raise _refused(CANNOT_CONFINE, _MESSAGES[CANNOT_CONFINE])


def _windows_children(fd: int) -> list[_Child]:
    import ctypes
    import msvcrt

    handle = msvcrt.get_osfhandle(fd)
    buffer = ctypes.create_string_buffer(1 << 16)
    children: list[_Child] = []
    info_class = _FULL_DIRECTORY_RESTART
    while True:
        if not _kernel32().GetFileInformationByHandleEx(handle, info_class, buffer, len(buffer)):
            code = ctypes.get_last_error()
            if code == _NO_MORE_FILES:
                return children
            raise ctypes.WinError(code)
        info_class = _FULL_DIRECTORY_INFO
        raw, offset = buffer.raw, 0
        while True:
            (following, _, _, _, _, _, size, _, attributes, length,
             tag) = _FULL_DIR_INFO.unpack_from(raw, offset)
            start = offset + _FULL_DIR_INFO.size
            name = raw[start:start + length].decode("utf-16-le")
            if name not in (".", ".."):
                link = bool(attributes & _ATTRIBUTE_REPARSE_POINT) and tag in (_TAG_SYMLINK,
                                                                              _TAG_MOUNT_POINT)
                directory = bool(attributes & _ATTRIBUTE_DIRECTORY)
                children.append(_Child(name, link, directory,
                                       None if directory or link else size))
            if not following:
                break
            offset += following


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
