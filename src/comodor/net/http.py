"""
requests — a production-grade, single-file HTTP client built only on the
Python standard library.

Why it exists
-------------
`requests` is excellent but it is a third-party dependency. In restricted
environments (CI runners, lambdas, air-gapped boxes, scrapers shipped as a
single file, GitHub Actions with no pip step) you often cannot install it.
This module gives you the same ergonomics with zero dependencies.

Feature set
-----------
* requests-style API: ``get/post/put/patch/delete/head/options/request``
* ``Session`` with connection pooling (HTTP keep-alive) and thread safety
* Automatic retries with exponential backoff + jitter, honouring ``Retry-After``
* Redirect handling (301/302/303/307/308) with correct method rewriting and
  ``Authorization`` stripping on cross-origin hops
* Cookie persistence via ``http.cookiejar``
* Transparent ``gzip`` / ``deflate`` / ``br`` / ``zstd`` decoding (br and zstd
  only when a codec is importable — otherwise they are not advertised)
* Streaming responses (``stream=True``, ``iter_content``, ``iter_lines``)
* ``json=`` bodies, urlencoded forms, raw bytes, file objects (chunked upload)
  and ``multipart/form-data`` uploads
* Modern TLS by default (TLS 1.2+, hostname check, system trust store),
  custom CA bundles, client certificates
* HTTP and HTTPS proxies (``CONNECT`` tunnelling) plus ``*_PROXY`` env vars
* Separate connect/read timeouts
* Response hooks and ``logging`` integration

Quick start
-----------
    import requests

    r = requests.get("https://api.github.com/repos/python/cpython",
                     timeout=(3, 10))
    r.raise_for_status()
    print(r.json()["stargazers_count"])

    with requests.Session(base_url="https://api.example.com",
                          headers={"Authorization": "Bearer ..."}) as s:
        s.post("/v1/items", json={"name": "x"}).raise_for_status()
        for item in s.get("/v1/items").json():
            print(item)

Compatible with CPython 3.9+.
"""

from __future__ import annotations

import base64
import email.utils
import io
import json as _jsonlib
import logging
import mimetypes
import os
import random
import select
import socket
import ssl
import sys
import threading
import time
import uuid
import zlib
from collections import deque
from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from datetime import timedelta
from http.client import (
    BadStatusLine,
    HTTPConnection,
    HTTPException,
    HTTPResponse,
    HTTPSConnection,
    IncompleteRead,
    RemoteDisconnected,
)
from http.cookiejar import Cookie, CookieJar
from typing import Any, Callable, Optional, Tuple, Union
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit
from urllib.request import getproxies, proxy_bypass

__version__ = "1.0.0"
__all__ = [
    # api
    "request", "get", "post", "put", "patch", "delete", "head", "options",
    "Session", "Response", "PreparedRequest",
    # config
    "Timeout", "Retry", "CaseInsensitiveDict",
    # auth
    "BasicAuth", "BearerAuth", "AuthBase",
    # exceptions
    "RequestError", "ConnectionFailed", "ProxyError", "SSLCertError",
    "HTTPTimeout", "ConnectTimeout", "ReadTimeout", "TooManyRedirects",
    "InvalidURL", "ContentDecodingError", "JSONDecodeError", "HTTPStatusError",
    "ChunkedEncodingError",
]

logger = logging.getLogger("requests")

# --------------------------------------------------------------------------- #
# optional codecs
# --------------------------------------------------------------------------- #

try:  # brotli (pip install brotli / brotlicffi) — optional
    import brotli as _brotli  # type: ignore
except ImportError:  # pragma: no cover
    try:
        import brotlicffi as _brotli  # type: ignore
    except ImportError:
        _brotli = None

_zstd_decompressor_factory: Optional[Callable[[], Any]] = None
try:  # Python 3.14+ ships zstd in the stdlib
    from compression.zstd import ZstdDecompressor as _StdZstdDecompressor  # type: ignore

    _zstd_decompressor_factory = _StdZstdDecompressor
except ImportError:  # pragma: no cover
    try:
        import zstandard as _zstandard  # type: ignore

        _zstd_decompressor_factory = lambda: _zstandard.ZstdDecompressor().decompressobj()  # noqa: E731
    except ImportError:
        _zstd_decompressor_factory = None


def _comodor_version() -> str:
    """The installed version, without importing the package into this module.

    `net.http` is imported by the package itself, so asking it for its own
    version at import time is a cycle. Read lazily, and never fatal - a user
    agent is not worth failing a request over.
    """
    try:
        from importlib.metadata import version

        return version("comodor")
    except Exception:
        return "0"


def _supported_encodings() -> str:
    encodings = ["gzip", "deflate"]
    if _brotli is not None:
        encodings.append("br")
    if _zstd_decompressor_factory is not None:
        encodings.append("zstd")
    return ", ".join(encodings)


#: Who is calling. This client is API-compatible with `requests` and was
#: naming itself as `requests` because of it - which is a statement about a
#: library nobody here is using, made to every provider on every request. A
#: user agent is an identity, not a compatibility shim, and a provider trying
#: to work out where its traffic comes from deserves the true answer.
DEFAULT_USER_AGENT = (
    f"Comodor/{_comodor_version()} "
    f"(+https://comodor.ai; python/{sys.version_info.major}."
    f"{sys.version_info.minor}; {sys.platform})"
)
DEFAULT_ACCEPT_ENCODING = _supported_encodings()
DEFAULT_CHUNK_SIZE = 64 * 1024
MAX_DRAIN_BYTES = 1 * 1024 * 1024  # body we are willing to read just to reuse a socket
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# --------------------------------------------------------------------------- #
# exceptions
# --------------------------------------------------------------------------- #


class RequestError(IOError):
    """Base class for every error raised by this module."""

    def __init__(self, message: str = "", *, request: "PreparedRequest | None" = None,
                 response: "Response | None" = None) -> None:
        super().__init__(message)
        self.request = request
        self.response = response


class InvalidURL(RequestError, ValueError):
    """The URL is malformed or uses an unsupported scheme."""


class ConnectionFailed(RequestError):
    """The TCP/TLS connection could not be established or was lost."""


class ProxyError(ConnectionFailed):
    """The proxy refused or broke the tunnel."""


class SSLCertError(ConnectionFailed):
    """TLS handshake or certificate verification failure."""


class HTTPTimeout(RequestError):
    """Base timeout error."""


class ConnectTimeout(HTTPTimeout, ConnectionFailed):
    """Timed out while establishing the connection."""


class ReadTimeout(HTTPTimeout):
    """The server did not send data within the read timeout."""


class TooManyRedirects(RequestError):
    """Redirect chain exceeded ``max_redirects``."""


class ContentDecodingError(RequestError):
    """Body could not be decompressed."""


class ChunkedEncodingError(RequestError):
    """The server broke the response framing mid-body."""


class JSONDecodeError(RequestError, ValueError):
    """Response body was not valid JSON."""


class HTTPStatusError(RequestError):
    """Raised by :meth:`Response.raise_for_status` for 4xx/5xx responses."""


# requests-compatible alias (handy when porting existing code)
RequestException = RequestError

# --------------------------------------------------------------------------- #
# containers
# --------------------------------------------------------------------------- #


class CaseInsensitiveDict(MutableMapping):
    """Dict with case-insensitive keys that remembers the original casing.

    HTTP header names are case-insensitive (RFC 9110 §5.1), so header handling
    must be too, while still sending back what the caller typed.
    """

    __slots__ = ("_store",)

    def __init__(self, data: Any = None, **kwargs: Any) -> None:
        self._store: dict[str, tuple[str, Any]] = {}
        if data is not None:
            self.update(data)
        if kwargs:
            self.update(kwargs)

    def __setitem__(self, key: str, value: Any) -> None:
        self._store[key.lower()] = (key, value)

    def __getitem__(self, key: str) -> Any:
        return self._store[key.lower()][1]

    def __delitem__(self, key: str) -> None:
        del self._store[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return (original for original, _ in self._store.values())

    def __len__(self) -> int:
        return len(self._store)

    def lower_items(self) -> Iterator[tuple[str, Any]]:
        return ((key, value[1]) for key, value in self._store.items())

    def copy(self) -> "CaseInsensitiveDict":
        new = CaseInsensitiveDict()
        new._store = dict(self._store)
        return new

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Mapping):
            other = CaseInsensitiveDict(other)
        else:
            return NotImplemented
        return dict(self.lower_items()) == dict(other.lower_items())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({dict(self.items())!r})"


def _merge_headers(*sources: Optional[Mapping[str, Any]]) -> CaseInsensitiveDict:
    """Merge header mappings left to right; a ``None`` value removes the key."""
    merged = CaseInsensitiveDict()
    for source in sources:
        if not source:
            continue
        for key, value in source.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
    return merged


# --------------------------------------------------------------------------- #
# timeout / retry policy
# --------------------------------------------------------------------------- #

TimeoutValue = Union[None, float, int, Tuple[Optional[float], Optional[float]], "Timeout"]


@dataclass(frozen=True)
class Timeout:
    """Separate connect and read deadlines (in seconds). ``None`` = no limit."""

    connect: Optional[float] = 10.0
    read: Optional[float] = 30.0

    @classmethod
    def coerce(cls, value: TimeoutValue) -> "Timeout":
        if value is None:
            return cls(None, None)
        if isinstance(value, Timeout):
            return value
        if isinstance(value, (int, float)):
            return cls(float(value), float(value))
        if isinstance(value, tuple):
            if len(value) != 2:
                raise ValueError("timeout tuple must be (connect, read)")
            connect, read = value
            return cls(
                None if connect is None else float(connect),
                None if read is None else float(read),
            )
        raise TypeError(f"unsupported timeout value: {value!r}")


@dataclass(frozen=True)
class Retry:
    """Retry policy.

    Only idempotent methods are retried by default; a POST is never replayed
    unless you explicitly opt in, because the server may have processed it.
    """

    total: int = 2
    backoff_factor: float = 0.4
    backoff_max: float = 20.0
    jitter: float = 0.25
    status_forcelist: frozenset = frozenset({408, 425, 429, 500, 502, 503, 504})
    allowed_methods: frozenset = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})
    respect_retry_after: bool = True
    retry_on_connection_error: bool = True

    def allows(self, method: str, attempt: int) -> bool:
        return attempt < self.total and method.upper() in self.allowed_methods

    def backoff(self, attempt: int) -> float:
        delay = min(self.backoff_max, self.backoff_factor * (2 ** attempt))
        return delay + random.uniform(0.0, self.jitter)

    def delay_for(self, attempt: int, retry_after: Optional[float]) -> Optional[float]:
        """Seconds to wait, or ``None`` when we should give up.

        If the server asks for a longer pause than ``backoff_max`` we do not
        retry at all — sleeping less would just burn the next attempt.
        """
        if self.respect_retry_after and retry_after is not None:
            if retry_after > self.backoff_max:
                return None
            return max(0.0, retry_after)
        return self.backoff(attempt)


NO_RETRY = Retry(total=0)

# --------------------------------------------------------------------------- #
# URL helpers
# --------------------------------------------------------------------------- #

_PATH_SAFE = "/%:@&=+$,~*!'();"
_QUERY_SAFE = "/%:@&=+$,~*!'();?"
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _idna_encode(host: str) -> str:
    """Punycode non-ASCII hostnames (e.g. ``ققنوس.com``) without extra deps."""
    if all(ord(ch) < 128 for ch in host):
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidURL(f"cannot encode hostname {host!r}: {exc}") from exc


def _encode_params(params: Any) -> str:
    """Turn dicts / sequences / raw strings into a query string.

    ``None`` values are dropped, sequences expand into repeated keys, and
    booleans are lowercased the way most APIs expect.
    """
    if params is None:
        return ""
    if isinstance(params, (str, bytes)):
        return params.decode("utf-8") if isinstance(params, bytes) else params
    if isinstance(params, Mapping):
        items = list(params.items())
    else:
        items = list(params)

    pairs: list[tuple[str, str]] = []
    for key, value in items:
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((str(key), "true" if value else "false"))
        elif isinstance(value, (list, tuple, set, frozenset)):
            for element in value:
                if element is None:
                    continue
                pairs.append((str(key), "true" if element is True else
                              "false" if element is False else str(element)))
        else:
            pairs.append((str(key), str(value)))
    return urlencode(pairs, doseq=False, quote_via=quote)


@dataclass
class _URL:
    scheme: str
    host: str
    port: int
    target: str            # origin-form: /path?query
    userinfo: Optional[tuple[str, str]]

    @property
    def host_header(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        if self.port == _DEFAULT_PORTS.get(self.scheme):
            return host
        return f"{host}:{self.port}"

    @property
    def origin(self) -> tuple[str, str, int]:
        return (self.scheme, self.host, self.port)

    def full_url(self) -> str:
        return f"{self.scheme}://{self.host_header}{self.target}"


def _parse_url(url: str, params: Any = None) -> _URL:
    if not isinstance(url, str):
        url = str(url)
    url = url.strip()
    parts = urlsplit(url)

    scheme = parts.scheme.lower()
    if not scheme:
        raise InvalidURL(f"missing scheme in URL: {url!r} (did you forget https://?)")
    if scheme not in _DEFAULT_PORTS:
        raise InvalidURL(f"unsupported scheme {scheme!r}; only http and https are supported")
    if not parts.hostname:
        raise InvalidURL(f"missing host in URL: {url!r}")

    host = _idna_encode(parts.hostname)
    try:
        port = parts.port or _DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise InvalidURL(f"invalid port in URL {url!r}: {exc}") from exc

    userinfo = None
    if parts.username is not None:
        userinfo = (parts.username, parts.password or "")

    path = quote(parts.path, safe=_PATH_SAFE) or "/"

    query = quote(parts.query, safe=_QUERY_SAFE)
    extra = _encode_params(params)
    if extra:
        query = f"{query}&{extra}" if query else extra

    target = f"{path}?{query}" if query else path
    return _URL(scheme=scheme, host=host, port=port, target=target, userinfo=userinfo)


def _resolve(base: Optional[str], url: str) -> str:
    """Join ``url`` onto a session ``base_url`` (httpx-style ergonomics)."""
    if not base:
        return url
    if urlsplit(url).scheme:
        return url
    if not base.endswith("/"):
        base += "/"
    return urljoin(base, url.lstrip("/"))


# --------------------------------------------------------------------------- #
# authentication
# --------------------------------------------------------------------------- #


class AuthBase:
    """Subclass and implement ``__call__`` to build custom auth schemes."""

    def __call__(self, request: "PreparedRequest") -> "PreparedRequest":
        raise NotImplementedError


class BasicAuth(AuthBase):
    """RFC 7617 Basic authentication."""

    def __init__(self, username: str, password: str = "") -> None:
        self.username = username
        self.password = password

    def header_value(self) -> str:
        raw = f"{self.username}:{self.password}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def __call__(self, request: "PreparedRequest") -> "PreparedRequest":
        request.headers["Authorization"] = self.header_value()
        return request


class BearerAuth(AuthBase):
    """``Authorization: Bearer <token>``."""

    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, request: "PreparedRequest") -> "PreparedRequest":
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


class _CallableAuth(AuthBase):
    """Wrap a plain function ``f(request) -> request`` as an auth handler."""

    def __init__(self, func: Callable[["PreparedRequest"], Any]) -> None:
        self._func = func

    def __call__(self, request: "PreparedRequest") -> "PreparedRequest":
        return self._func(request) or request


def _coerce_auth(auth: Any) -> Optional[AuthBase]:
    if auth is None:
        return None
    if isinstance(auth, AuthBase):
        return auth
    if isinstance(auth, tuple) and len(auth) == 2:
        return BasicAuth(str(auth[0]), str(auth[1]))
    if callable(auth):
        return _CallableAuth(auth)
    raise TypeError(f"unsupported auth value: {auth!r}")


# --------------------------------------------------------------------------- #
# cookie plumbing (adapters so http.cookiejar can talk to our objects)
# --------------------------------------------------------------------------- #


class _CookieRequestAdapter:
    """Minimal ``urllib.request.Request`` lookalike for ``CookieJar``."""

    def __init__(self, prepared: "PreparedRequest") -> None:
        self._r = prepared

    def get_full_url(self) -> str:
        return self._r.url

    def get_host(self) -> str:
        return self._r.parsed.host_header

    @property
    def host(self) -> str:
        return self._r.parsed.host_header

    @property
    def type(self) -> str:
        return self._r.parsed.scheme

    @property
    def origin_req_host(self) -> str:
        return self._r.parsed.host

    @property
    def unverifiable(self) -> bool:
        return False

    def is_unverifiable(self) -> bool:
        return False

    def get_origin_req_host(self) -> str:
        return self._r.parsed.host

    def has_header(self, name: str) -> bool:
        return name in self._r.headers

    def get_header(self, name: str, default: Any = None) -> Any:
        return self._r.headers.get(name, default)

    def header_items(self) -> list[tuple[str, Any]]:
        return list(self._r.headers.items())

    def add_header(self, key: str, value: str) -> None:
        self._r.headers[key] = value

    def add_unredirected_header(self, key: str, value: str) -> None:
        self._r.headers[key] = value


class _CookieResponseAdapter:
    """Minimal response lookalike: ``CookieJar`` only needs ``info()``."""

    def __init__(self, raw: HTTPResponse) -> None:
        self._msg = raw.msg

    def info(self):  # noqa: D401 - cookiejar protocol
        return self._msg

    def getheaders(self, name: str) -> list[str]:
        return self._msg.get_all(name, [])


def cookiejar_from_dict(cookies: Optional[Mapping[str, str]],
                        jar: Optional[CookieJar] = None,
                        domain: str = "") -> CookieJar:
    """Build (or extend) a ``CookieJar`` from a plain ``{name: value}`` dict."""
    jar = jar if jar is not None else CookieJar()
    for name, value in (cookies or {}).items():
        jar.set_cookie(Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=bool(domain), domain_initial_dot=False,
            path="/", path_specified=True, secure=False, expires=None, discard=True,
            comment=None, comment_url=None, rest={}, rfc2109=False,
        ))
    return jar


def _jar_as_dict(jar: CookieJar) -> dict[str, str]:
    return {cookie.name: cookie.value for cookie in jar}


# --------------------------------------------------------------------------- #
# body encoders
# --------------------------------------------------------------------------- #

BodyType = Union[None, bytes, bytearray, str, Mapping, Iterable, io.IOBase]


def _guess_content_type(filename: Optional[str]) -> str:
    if not filename:
        return "application/octet-stream"
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


#: One part of a multipart body: the field name, then the filename, the
#: payload, its content type, and any extra headers.
_FilePart = tuple[str, tuple[Optional[str], Any, Optional[str],
                             Optional[Mapping[str, str]]]]


def _normalize_files(files: Any) -> list[_FilePart]:
    """Accept requests-style ``files=`` in all of its shapes."""
    if isinstance(files, Mapping):
        items = list(files.items())
    else:
        items = list(files)

    normalized = []
    for field_name, spec in items:
        filename: Optional[str] = None
        content_type: Optional[str] = None
        extra_headers: Optional[Mapping[str, str]] = None

        if isinstance(spec, (tuple, list)):
            if len(spec) == 2:
                filename, payload = spec
            elif len(spec) == 3:
                filename, payload, content_type = spec
            elif len(spec) == 4:
                filename, payload, content_type, extra_headers = spec
            else:
                raise ValueError(f"invalid files entry for {field_name!r}")
        else:
            payload = spec
            filename = getattr(payload, "name", None)
            if filename:
                filename = os.path.basename(str(filename))
        normalized.append((str(field_name), (filename, payload, content_type, extra_headers)))
    return normalized


def _encode_multipart(data: Any, files: Any) -> tuple[bytes, str]:
    """Build a ``multipart/form-data`` body and return ``(body, content_type)``.

    The body is assembled in memory so an exact ``Content-Length`` can be sent
    (many servers and CDNs reject chunked uploads). For multi-gigabyte payloads
    pass an open file object as ``data=`` instead — that streams chunked.
    """
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    buffer = io.BytesIO()

    def _write_field(name: str, value: Any, filename: Optional[str] = None,
                     content_type: Optional[str] = None,
                     extra_headers: Optional[Mapping[str, str]] = None) -> None:
        buffer.write(b"--" + boundary.encode("ascii") + crlf)
        disposition = f'form-data; name="{_escape_quotes(name)}"'
        if filename is not None:
            disposition += f'; filename="{_escape_quotes(filename)}"'
            # RFC 5987 for non-ASCII names, so Persian filenames survive.
            if any(ord(ch) > 127 for ch in filename):
                disposition += f"; filename*=UTF-8''{quote(filename, safe='')}"
        buffer.write(f"Content-Disposition: {disposition}".encode("utf-8") + crlf)
        if content_type:
            buffer.write(f"Content-Type: {content_type}".encode("utf-8") + crlf)
        for header_name, header_value in (extra_headers or {}).items():
            buffer.write(f"{header_name}: {header_value}".encode("utf-8") + crlf)
        buffer.write(crlf)
        buffer.write(_to_bytes(value))
        buffer.write(crlf)

    if data:
        pairs = data.items() if isinstance(data, Mapping) else data
        for name, value in pairs:
            if value is None:
                continue
            if isinstance(value, (list, tuple, set, frozenset)):
                for element in value:
                    _write_field(str(name), element)
            else:
                _write_field(str(name), value)

    for field_name, (filename, payload, content_type, extra_headers) in \
            _normalize_files(files or {}):
        if hasattr(payload, "read"):
            payload = payload.read()
        _write_field(
            field_name,
            payload,
            filename=filename if filename is not None else field_name,
            content_type=content_type or _guess_content_type(filename),
            extra_headers=extra_headers,
        )

    buffer.write(b"--" + boundary.encode("ascii") + b"--" + crlf)
    return buffer.getvalue(), f"multipart/form-data; boundary={boundary}"


def _escape_quotes(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bool):
        return b"true" if value else b"false"
    return str(value).encode("utf-8")


# --------------------------------------------------------------------------- #
# content decoders
# --------------------------------------------------------------------------- #


class _Decoder:
    def decompress(self, chunk: bytes) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def flush(self) -> bytes:  # pragma: no cover - interface
        return b""


class _ZlibDecoder(_Decoder):
    """gzip / deflate, tolerant of servers that send raw deflate."""

    def __init__(self, wbits: int, lenient: bool = False) -> None:
        self._wbits = wbits
        self._lenient = lenient
        self._obj = zlib.decompressobj(wbits)
        self._first = True

    def decompress(self, chunk: bytes) -> bytes:
        if not chunk:
            return b""
        try:
            out = self._obj.decompress(chunk)
        except zlib.error:
            if self._first and self._lenient:
                # Some servers label raw deflate streams as "deflate".
                self._obj = zlib.decompressobj(-zlib.MAX_WBITS)
                out = self._obj.decompress(chunk)
            else:
                raise
        self._first = False
        return out

    def flush(self) -> bytes:
        try:
            return self._obj.flush()
        except zlib.error:
            return b""


class _BrotliDecoder(_Decoder):
    def __init__(self) -> None:
        self._obj = _brotli.Decompressor()

    def decompress(self, chunk: bytes) -> bytes:
        if not chunk:
            return b""
        if hasattr(self._obj, "decompress"):
            return self._obj.decompress(chunk)
        return self._obj.process(chunk)  # pragma: no cover - brotlipy fallback


class _ZstdDecoder(_Decoder):
    def __init__(self) -> None:
        self._obj = _zstd_decompressor_factory()

    def decompress(self, chunk: bytes) -> bytes:
        if not chunk:
            return b""
        return self._obj.decompress(chunk)


class _ChainDecoder(_Decoder):
    def __init__(self, decoders: list[_Decoder]) -> None:
        self._decoders = decoders

    def decompress(self, chunk: bytes) -> bytes:
        for decoder in self._decoders:
            chunk = decoder.decompress(chunk)
        return chunk

    def flush(self) -> bytes:
        tail = b""
        for decoder in self._decoders:
            tail = decoder.decompress(tail) if tail else tail
            tail += decoder.flush()
        return tail


def _build_decoder(content_encoding: str) -> Optional[_Decoder]:
    """``Content-Encoding: gzip, br`` means br was applied last → undo first."""
    tokens = [token.strip().lower() for token in content_encoding.split(",") if token.strip()]
    tokens = [token for token in tokens if token not in ("identity", "")]
    if not tokens:
        return None

    decoders: list[_Decoder] = []
    for token in reversed(tokens):
        if token in ("gzip", "x-gzip"):
            decoders.append(_ZlibDecoder(16 + zlib.MAX_WBITS))
        elif token == "deflate":
            decoders.append(_ZlibDecoder(zlib.MAX_WBITS, lenient=True))
        elif token == "br":
            if _brotli is None:
                raise ContentDecodingError(
                    "server replied with brotli but no brotli codec is installed"
                )
            decoders.append(_BrotliDecoder())
        elif token == "zstd":
            if _zstd_decompressor_factory is None:
                raise ContentDecodingError(
                    "server replied with zstd but no zstd codec is available"
                )
            decoders.append(_ZstdDecoder())
        else:
            raise ContentDecodingError(f"unsupported content-encoding: {token!r}")

    return decoders[0] if len(decoders) == 1 else _ChainDecoder(decoders)


# --------------------------------------------------------------------------- #
# prepared request
# --------------------------------------------------------------------------- #


@dataclass
class PreparedRequest:
    """A fully materialised request: method, URL, headers and body bytes."""

    method: str
    url: str
    parsed: _URL
    headers: CaseInsensitiveDict
    body: Any = None
    replayable: bool = True   # False for file/generator bodies (cannot retry)

    def copy(self) -> "PreparedRequest":
        return _dc_replace(self, headers=self.headers.copy())

    def __repr__(self) -> str:
        return f"<PreparedRequest [{self.method} {self.url}]>"


def build_request(
    method: str,
    url: str,
    *,
    params: Any = None,
    data: BodyType = None,
    json: Any = None,
    files: Any = None,
    headers: Optional[Mapping[str, Any]] = None,
    auth: Any = None,
    json_dumps: Callable[[Any], str] = None,
) -> PreparedRequest:
    """Normalise every user-facing argument into a :class:`PreparedRequest`."""
    method = method.upper()
    parsed = _parse_url(url, params)
    final_headers = _merge_headers(headers)
    replayable = True
    body: Any = None

    if files:
        if json is not None:
            raise ValueError("cannot combine files= with json=")
        body, content_type = _encode_multipart(data, files)
        final_headers.setdefault("Content-Type", content_type)
    elif json is not None:
        if data is not None:
            raise ValueError("cannot combine data= with json=")
        dumps = json_dumps or (lambda obj: _jsonlib.dumps(
            obj, ensure_ascii=False, separators=(",", ":"), default=str))
        body = dumps(json).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    elif data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, Mapping) or (
            isinstance(data, (list, tuple)) and all(
                isinstance(item, (list, tuple)) and len(item) == 2 for item in data)
        ):
            body = _encode_params(data).encode("ascii")
            final_headers.setdefault("Content-Type",
                                     "application/x-www-form-urlencoded")
        elif hasattr(data, "read") or isinstance(data, Iterable):
            # streamed upload: http.client will use Transfer-Encoding: chunked
            body = data
            replayable = False
        else:
            raise TypeError(f"unsupported data type: {type(data).__name__}")

    final_headers.setdefault("Host", parsed.host_header)
    final_headers.setdefault("Accept", "*/*")
    final_headers.setdefault("Accept-Encoding", DEFAULT_ACCEPT_ENCODING)
    final_headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
    final_headers.setdefault("Connection", "keep-alive")

    request = PreparedRequest(
        method=method,
        url=parsed.full_url(),
        parsed=parsed,
        headers=final_headers,
        body=body,
        replayable=replayable,
    )

    # credentials embedded in the URL (https://user:pass@host/) unless overridden
    if auth is None and parsed.userinfo is not None:
        auth = BasicAuth(*parsed.userinfo)
    auth_handler = _coerce_auth(auth)
    if auth_handler is not None:
        request = auth_handler(request) or request
    return request


# --------------------------------------------------------------------------- #
# response
# --------------------------------------------------------------------------- #


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())


class Response:
    """The result of a request. Behaves like ``requests.Response``."""

    __slots__ = (
        "status_code", "reason", "headers", "url", "request", "raw", "history",
        "cookies", "elapsed", "_content", "_decoder", "_released", "_release_cb",
        "_consumed", "_encoding", "_stream",
    )

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        headers: CaseInsensitiveDict,
        url: str,
        request: PreparedRequest,
        raw: Optional[HTTPResponse],
        cookies: CookieJar,
        elapsed: float,
        release_cb: Optional[Callable[[bool], None]] = None,
        stream: bool = False,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.headers = headers
        self.url = url
        self.request = request
        self.raw = raw
        self.cookies = cookies
        self.elapsed = timedelta(seconds=elapsed)
        self.history: list["Response"] = []
        self._content: Optional[bytes] = None
        self._decoder = _build_decoder(headers.get("Content-Encoding", ""))
        self._release_cb = release_cb
        self._released = False
        self._consumed = False
        self._encoding: Optional[str] = None
        self._stream = stream

    # -- lifecycle -------------------------------------------------------- #

    def _release(self, reusable: bool) -> None:
        if self._released:
            return
        self._released = True
        if self._release_cb is not None:
            try:
                self._release_cb(reusable)
            except Exception:  # pragma: no cover - never let cleanup mask errors
                logger.debug("connection release failed", exc_info=True)

    def close(self) -> None:
        """Release the underlying connection (safe to call repeatedly)."""
        raw = self.raw
        reusable = False
        if raw is not None:
            try:
                reusable = bool(raw.isclosed()) and not raw.will_close
            except Exception:
                reusable = False
        self._release(reusable)

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.close()
        except Exception:
            pass

    # -- body ------------------------------------------------------------- #

    def iter_raw(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """Iterate the body exactly as it arrived (still compressed)."""
        if self._consumed:
            raise RuntimeError("response body already consumed")
        self._consumed = True
        raw = self.raw
        if raw is None:
            return
        try:
            while True:
                chunk = raw.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        except (socket.timeout, TimeoutError) as exc:
            self._release(False)
            raise ReadTimeout(f"read timed out while streaming: {exc}",
                              request=self.request, response=self) from exc
        except IncompleteRead as exc:
            self._release(False)
            raise ChunkedEncodingError(f"broken response body: {exc}",
                                       request=self.request, response=self) from exc
        except (HTTPException, OSError) as exc:
            self._release(False)
            raise ConnectionFailed(f"connection lost while reading body: {exc}",
                                   request=self.request, response=self) from exc
        else:
            self.close()

    def iter_content(self, chunk_size: int = DEFAULT_CHUNK_SIZE,
                     decode_unicode: bool = False) -> Iterator[Any]:
        """Iterate the decompressed body in chunks."""
        if self._content is not None:
            data: Any = self._content
            if decode_unicode:
                data = data.decode(self.encoding, errors="replace")
            yield data
            return

        decoder = self._decoder
        for chunk in self.iter_raw(chunk_size):
            if decoder is not None:
                try:
                    chunk = decoder.decompress(chunk)
                except Exception as exc:
                    raise ContentDecodingError(f"failed to decode body: {exc}",
                                               request=self.request, response=self) from exc
            if chunk:
                yield chunk.decode(self.encoding, errors="replace") if decode_unicode else chunk
        if decoder is not None:
            try:
                tail = decoder.flush()
            except Exception:
                tail = b""
            if tail:
                yield tail.decode(self.encoding, errors="replace") if decode_unicode else tail

    def iter_lines(self, chunk_size: int = DEFAULT_CHUNK_SIZE,
                   decode_unicode: bool = False,
                   delimiter: bytes = b"\n") -> Iterator[Any]:
        """Iterate the body line by line (handy for NDJSON / SSE streams)."""
        buffer = b""
        for chunk in self.iter_content(chunk_size):
            buffer += chunk
            while delimiter in buffer:
                line, buffer = buffer.split(delimiter, 1)
                line = line.rstrip(b"\r")
                yield line.decode(self.encoding, errors="replace") if decode_unicode else line
        if buffer:
            buffer = buffer.rstrip(b"\r")
            yield buffer.decode(self.encoding, errors="replace") if decode_unicode else buffer

    def read(self) -> bytes:
        """Read (and cache) the whole decompressed body."""
        if self._content is None:
            self._content = b"".join(self.iter_content())
        return self._content

    @property
    def content(self) -> bytes:
        return self.read()

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self, **kwargs: Any) -> Any:
        try:
            return _jsonlib.loads(self.text, **kwargs)
        except ValueError as exc:
            raise JSONDecodeError(f"response is not valid JSON: {exc}",
                                  request=self.request, response=self) from exc

    # -- metadata --------------------------------------------------------- #

    @property
    def encoding(self) -> str:
        if self._encoding:
            return self._encoding
        content_type = self.headers.get("Content-Type", "")
        for parameter in content_type.split(";")[1:]:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "charset":
                charset = value.strip().strip('"\'')
                if charset:
                    self._encoding = charset
                    return charset
        media_type = content_type.split(";")[0].strip().lower()
        if media_type.endswith(("json", "+json")):
            self._encoding = "utf-8"
        elif media_type.startswith("text/"):
            # RFC 9110 default, but modern servers are almost always UTF-8.
            self._encoding = self._sniff_encoding() or "utf-8"
        else:
            self._encoding = self._sniff_encoding() or "utf-8"
        return self._encoding

    @encoding.setter
    def encoding(self, value: str) -> None:
        self._encoding = value

    def _sniff_encoding(self) -> Optional[str]:
        if self._content is None:
            return None
        try:
            self._content.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            return "iso-8859-1"

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def is_redirect(self) -> bool:
        return self.status_code in REDIRECT_STATUSES and "Location" in self.headers

    @property
    def retry_after(self) -> Optional[float]:
        return _parse_retry_after(self.headers.get("Retry-After"))

    @property
    def links(self) -> dict[str, dict[str, str]]:
        """Parse the ``Link`` header (RFC 8288) — used by paginated APIs."""
        header = self.headers.get("Link")
        result: dict[str, dict[str, str]] = {}
        if not header:
            return result
        for entry in header.split(","):
            entry = entry.strip()
            if not entry.startswith("<"):
                continue
            url_part, _, rest = entry.partition(">")
            link: dict[str, str] = {"url": url_part[1:].strip()}
            for parameter in rest.split(";"):
                key, _, value = parameter.partition("=")
                key, value = key.strip(), value.strip().strip('"')
                if key:
                    link[key] = value
            result[link.get("rel", link["url"])] = link
        return result

    def raise_for_status(self) -> "Response":
        if 400 <= self.status_code < 600:
            kind = "client" if self.status_code < 500 else "server"
            snippet = ""
            if not self._stream:
                try:
                    snippet = self.text[:512].replace("\n", " ")
                except Exception:
                    snippet = ""
            raise HTTPStatusError(
                f"{self.status_code} {self.reason} ({kind} error) for "
                f"{self.request.method} {self.url}" + (f" :: {snippet}" if snippet else ""),
                request=self.request,
                response=self,
            )
        return self

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return f"<Response [{self.status_code} {self.reason}]>"


# --------------------------------------------------------------------------- #
# TLS contexts + connection pool
# --------------------------------------------------------------------------- #

_ssl_context_cache: dict[tuple, ssl.SSLContext] = {}
_ssl_context_lock = threading.Lock()


def _build_ssl_context(verify: Union[bool, str],
                       cert: Union[None, str, tuple[str, str]]) -> ssl.SSLContext:
    """Create (and cache) a hardened TLS context."""
    key = (verify if isinstance(verify, (bool, str)) else bool(verify),
           cert if isinstance(cert, str) else tuple(cert) if cert else None)
    with _ssl_context_lock:
        context = _ssl_context_cache.get(key)
        if context is not None:
            return context

        if isinstance(verify, str):
            if os.path.isdir(verify):
                context = ssl.create_default_context(capath=verify)
            else:
                context = ssl.create_default_context(cafile=verify)
        else:
            context = ssl.create_default_context()

        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = bool(verify)
        context.verify_mode = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
        try:
            context.set_alpn_protocols(["http/1.1"])
        except NotImplementedError:  # pragma: no cover
            pass
        if not verify:
            logger.warning("TLS verification disabled — traffic is vulnerable to MITM")

        if cert:
            if isinstance(cert, str):
                context.load_cert_chain(cert)
            else:
                context.load_cert_chain(cert[0], cert[1] if len(cert) > 1 else None)

        _ssl_context_cache[key] = context
        return context


def _socket_is_dead(sock: Optional[socket.socket]) -> bool:
    """A pooled socket that is readable before we wrote anything is closed/EOF."""
    if sock is None:
        return True
    try:
        readable, _, errored = select.select([sock], [], [sock], 0)
    except (OSError, ValueError):
        return True
    return bool(readable or errored)


PoolKey = Tuple[str, str, int, str, Any]


class ConnectionPool:
    """Thread-safe keep-alive pool of ``http.client`` connections."""

    def __init__(self, per_host: int = 10, max_idle_seconds: float = 90.0) -> None:
        self.per_host = per_host
        self.max_idle_seconds = max_idle_seconds
        self._idle: dict[PoolKey, deque] = {}
        self._lock = threading.Lock()

    def acquire(self, key: PoolKey) -> Optional[HTTPConnection]:
        now = time.monotonic()
        with self._lock:
            bucket = self._idle.get(key)
            while bucket:
                connection, stored_at = bucket.pop()
                if now - stored_at > self.max_idle_seconds or _socket_is_dead(connection.sock):
                    _safe_close(connection)
                    continue
                return connection
        return None

    def release(self, key: PoolKey, connection: HTTPConnection) -> None:
        with self._lock:
            bucket = self._idle.setdefault(key, deque())
            if len(bucket) >= self.per_host:
                oldest, _ = bucket.popleft()
                _safe_close(oldest)
            bucket.append((connection, time.monotonic()))

    def clear(self) -> None:
        with self._lock:
            for bucket in self._idle.values():
                while bucket:
                    connection, _ = bucket.pop()
                    _safe_close(connection)
            self._idle.clear()

    @property
    def idle_count(self) -> int:
        with self._lock:
            return sum(len(bucket) for bucket in self._idle.values())


def _safe_close(connection: HTTPConnection) -> None:
    try:
        connection.close()
    except Exception:  # pragma: no cover
        pass


def _apply_read_timeout(connection: HTTPConnection, read_timeout: Optional[float]) -> None:
    """Re-arm the socket deadline (pooled sockets keep the previous one)."""
    connection.timeout = read_timeout
    if connection.sock is not None:
        try:
            connection.sock.settimeout(read_timeout)
        except OSError:  # pragma: no cover
            pass


_GLOBAL_POOL = ConnectionPool()


# --------------------------------------------------------------------------- #
# proxy resolution
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Proxy:
    scheme: str
    host: str
    port: int
    auth_header: Optional[str]

    @property
    def key(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _parse_proxy(raw: str) -> _Proxy:
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidURL(f"unsupported proxy scheme: {scheme!r}")
    if not parts.hostname:
        raise InvalidURL(f"invalid proxy URL: {raw!r}")
    header = None
    if parts.username:
        header = BasicAuth(parts.username, parts.password or "").header_value()
    return _Proxy(scheme, parts.hostname,
                  parts.port or _DEFAULT_PORTS[scheme], header)


def _select_proxy(url: _URL, proxies: Optional[Mapping[str, str]],
                  trust_env: bool) -> Optional[_Proxy]:
    merged: dict[str, str] = {}
    if trust_env:
        merged.update({k.lower(): v for k, v in getproxies().items()})
    if proxies:
        merged.update({k.lower(): v for k, v in proxies.items() if v})

    if not merged:
        return None
    if trust_env and not (proxies or {}).get(url.scheme):
        try:
            if proxy_bypass(url.host):
                return None
        except Exception:  # pragma: no cover - platform specific
            pass
    no_proxy = merged.get("no_proxy") or merged.get("no")
    if no_proxy and _matches_no_proxy(url.host, no_proxy):
        return None

    raw = (merged.get(f"{url.scheme}://{url.host_header}")
           or merged.get(url.scheme)
           or merged.get("all"))
    return _parse_proxy(raw) if raw else None


def _matches_no_proxy(host: str, no_proxy: str) -> bool:
    host = host.lower().rstrip(".")
    for entry in no_proxy.replace(",", " ").split():
        entry = entry.strip().lower().lstrip(".").rstrip(".")
        if not entry:
            continue
        if entry == "*":
            return True
        if host == entry or host.endswith("." + entry):
            return True
    return False


# --------------------------------------------------------------------------- #
# session
# --------------------------------------------------------------------------- #

HookType = Callable[[Response], Optional[Response]]


class Session:
    """Reusable client: keep-alive pooling, cookies, defaults, retries.

    A ``Session`` is safe to share between threads. Instances hold sockets, so
    close them (or use ``with``) when you are done.
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        headers: Optional[Mapping[str, Any]] = None,
        params: Any = None,
        auth: Any = None,
        cookies: Optional[Union[CookieJar, Mapping[str, str]]] = None,
        # Frozen dataclasses: one shared instance is the point, not a
        # mutable default waiting to be scribbled on.
        timeout: TimeoutValue = Timeout(),   # noqa: B008
        retry: Retry = Retry(),              # noqa: B008
        verify: Union[bool, str] = True,
        cert: Union[None, str, tuple[str, str]] = None,
        proxies: Optional[Mapping[str, str]] = None,
        trust_env: bool = True,
        max_redirects: int = 20,
        pool: Optional[ConnectionPool] = None,
        hooks: Optional[Mapping[str, list[HookType]]] = None,
        url_guard: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.base_url = base_url
        self.headers = _merge_headers(headers)
        self.params = params
        self.auth = auth
        self.cookies = (cookies if isinstance(cookies, CookieJar)
                        else cookiejar_from_dict(cookies))
        self.timeout = Timeout.coerce(timeout)
        self.retry = retry
        self.verify = verify
        self.cert = cert
        self.proxies = dict(proxies or {})
        self.trust_env = trust_env
        self.max_redirects = max_redirects
        self.hooks: dict[str, list[HookType]] = {
            "response": list((hooks or {}).get("response", []))}
        #: Called with the full URL before every connection — including every
        #: redirect hop, because each hop is re-prepared and re-sent through
        #: the same path. ``None`` means no guard: the session trusts whoever
        #: built it. Comodor's own traffic (providers, channels) is unguarded;
        #: sessions built for the model's tools carry the guard.
        self.url_guard = url_guard
        self._pool = pool if pool is not None else ConnectionPool()
        self._owns_pool = pool is None
        self._cookie_lock = threading.Lock()

    # -- context manager -------------------------------------------------- #

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_pool:
            self._pool.clear()

    # -- public API ------------------------------------------------------- #

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        data: BodyType = None,
        json: Any = None,
        files: Any = None,
        headers: Optional[Mapping[str, Any]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        auth: Any = None,
        timeout: Any = ...,
        allow_redirects: bool = True,
        max_redirects: Optional[int] = None,
        stream: bool = False,
        verify: Any = ...,
        cert: Any = ...,
        proxies: Optional[Mapping[str, str]] = None,
        retry: Optional[Retry] = None,
        hooks: Optional[Mapping[str, list[HookType]]] = None,
    ) -> Response:
        """Send a request and return a :class:`Response`.

        ``...`` (Ellipsis) means "inherit from the session" for ``timeout``,
        ``verify`` and ``cert`` — that way ``timeout=None`` can still mean
        "no timeout at all".
        """
        effective_timeout = self.timeout if timeout is ... else Timeout.coerce(timeout)
        effective_verify = self.verify if verify is ... else verify
        effective_cert = self.cert if cert is ... else cert
        effective_retry = retry if retry is not None else self.retry
        limit = self.max_redirects if max_redirects is None else max_redirects

        merged_params = _merge_params(self.params, params)
        merged_headers = _merge_headers(self.headers, headers)
        target = _resolve(self.base_url, url)

        prepared = build_request(
            method, target,
            params=merged_params, data=data, json=json, files=files,
            headers=merged_headers, auth=auth if auth is not None else self.auth,
        )

        with self._cookie_lock:
            jar = self.cookies
            if cookies:
                jar = cookiejar_from_dict(cookies, _clone_jar(jar))
        self._apply_cookies(prepared, jar)

        response = self._send(
            prepared,
            jar=jar,
            timeout=effective_timeout,
            allow_redirects=allow_redirects,
            max_redirects=limit,
            stream=stream,
            verify=effective_verify,
            cert=effective_cert,
            proxies=proxies,
            retry=effective_retry,
        )

        for hook in list(self.hooks.get("response", [])) + list((hooks or {}).get("response", [])):
            response = hook(response) or response
        return response

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> Response:
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("allow_redirects", False)
        return self.request("HEAD", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    # -- redirect / retry loop -------------------------------------------- #

    def _send(
        self,
        prepared: PreparedRequest,
        *,
        jar: CookieJar,
        timeout: Timeout,
        allow_redirects: bool,
        max_redirects: int,
        stream: bool,
        verify: Union[bool, str],
        cert: Any,
        proxies: Optional[Mapping[str, str]],
        retry: Retry,
    ) -> Response:
        history: list[Response] = []
        current = prepared

        while True:
            if self.url_guard is not None:
                # Per hop: each redirect re-enters this loop with the new
                # URL, so a hop to an internal address is refused before its
                # connection opens.
                self.url_guard(current.url)
            response = self._send_with_retry(
                current, jar=jar, timeout=timeout, stream=stream,
                verify=verify, cert=cert, proxies=proxies, retry=retry,
            )
            response.history = list(history)

            if not (allow_redirects and response.is_redirect):
                return response

            if len(history) >= max_redirects:
                response.close()
                raise TooManyRedirects(
                    f"exceeded {max_redirects} redirects (last: {response.url})",
                    request=current, response=response,
                )

            nxt = self._build_redirect(current, response, jar)
            _drain(response)
            history.append(response)
            current = nxt
            logger.debug("redirect %s -> %s", response.status_code, current.url)

    def _build_redirect(self, current: PreparedRequest, response: Response,
                        jar: CookieJar) -> PreparedRequest:
        location = response.headers.get("Location", "")
        try:
            new_url = urljoin(response.url, location.strip())
        except Exception as exc:
            raise InvalidURL(f"invalid Location header: {location!r}",
                             request=current, response=response) from exc

        method = current.method
        body = current.body
        headers = current.headers.copy()

        if response.status_code == 303 and method != "HEAD":
            method, body = "GET", None
        elif response.status_code in (301, 302) and method == "POST":
            method, body = "GET", None

        if body is None:
            for header in ("Content-Length", "Content-Type", "Transfer-Encoding"):
                headers.pop(header, None)

        parsed = _parse_url(new_url)
        if parsed.origin != current.parsed.origin:
            # never leak credentials to a different origin
            headers.pop("Authorization", None)
            headers.pop("Proxy-Authorization", None)
            headers.pop("Cookie", None)
        headers["Host"] = parsed.host_header

        redirected = PreparedRequest(
            method=method, url=parsed.full_url(), parsed=parsed,
            headers=headers, body=body, replayable=current.replayable,
        )
        self._apply_cookies(redirected, jar)
        return redirected

    def _send_with_retry(
        self,
        prepared: PreparedRequest,
        *,
        jar: CookieJar,
        timeout: Timeout,
        stream: bool,
        verify: Union[bool, str],
        cert: Any,
        proxies: Optional[Mapping[str, str]],
        retry: Retry,
    ) -> Response:
        attempt = 0
        while True:
            try:
                response = self._transmit(
                    prepared, jar=jar, timeout=timeout, stream=stream,
                    verify=verify, cert=cert, proxies=proxies,
                )
            except (ConnectionFailed, HTTPTimeout) as exc:
                can_retry = (
                    retry.retry_on_connection_error
                    and prepared.replayable
                    and retry.allows(prepared.method, attempt)
                )
                if not can_retry:
                    raise
                delay = retry.backoff(attempt)
                logger.debug("retrying after %s in %.2fs (attempt %d)",
                             type(exc).__name__, delay, attempt + 1)
                time.sleep(delay)
                attempt += 1
                continue

            if (response.status_code in retry.status_forcelist
                    and prepared.replayable
                    and retry.allows(prepared.method, attempt)):
                delay = retry.delay_for(attempt, response.retry_after)
                if delay is None:
                    return response
                _drain(response)
                logger.debug("retrying HTTP %d in %.2fs (attempt %d)",
                             response.status_code, delay, attempt + 1)
                time.sleep(delay)
                attempt += 1
                continue

            return response

    # -- single round trip ------------------------------------------------ #

    def _transmit(
        self,
        prepared: PreparedRequest,
        *,
        jar: CookieJar,
        timeout: Timeout,
        stream: bool,
        verify: Union[bool, str],
        cert: Any,
        proxies: Optional[Mapping[str, str]],
    ) -> Response:
        url = prepared.parsed
        proxy = _select_proxy(url, proxies if proxies is not None else self.proxies,
                              self.trust_env)
        ssl_key: Any = None
        if url.scheme == "https":
            ssl_key = (verify if isinstance(verify, (bool, str)) else bool(verify),
                       cert if isinstance(cert, str) else tuple(cert) if cert else None)
        key: PoolKey = (url.scheme, url.host, url.port,
                        proxy.key if proxy else "", ssl_key)

        headers = dict(prepared.headers.items())
        request_target = url.target
        if proxy is not None and url.scheme == "http":
            request_target = prepared.url  # absolute-form for plain HTTP proxies
            if proxy.auth_header:
                headers["Proxy-Authorization"] = proxy.auth_header

        connection = self._pool.acquire(key)
        reused = connection is not None
        started = time.monotonic()

        for round_trip in range(2):
            if connection is None:
                connection = self._open(url, proxy, timeout, verify, cert)
                reused = False
            else:
                # a pooled socket still carries the previous call's deadline
                _apply_read_timeout(connection, timeout.read)
            try:
                connection.request(prepared.method, request_target,
                                   body=prepared.body, headers=headers)
                raw = connection.getresponse()
                break
            except (RemoteDisconnected, BadStatusLine, ConnectionResetError,
                    BrokenPipeError) as exc:
                _safe_close(connection)
                connection = None
                if reused and prepared.replayable and round_trip == 0:
                    # A pooled socket died between requests — normal, retry once.
                    logger.debug("stale pooled connection, reconnecting: %s", exc)
                    reused = False
                    continue
                raise ConnectionFailed(f"connection closed by peer: {exc}",
                                       request=prepared) from exc
            except (socket.timeout, TimeoutError) as exc:
                _safe_close(connection)
                raise ReadTimeout(f"server did not respond within "
                                  f"{timeout.read}s: {exc}", request=prepared) from exc
            except ssl.SSLError as exc:
                _safe_close(connection)
                raise SSLCertError(f"TLS error: {exc}", request=prepared) from exc
            except (HTTPException, OSError) as exc:
                _safe_close(connection)
                raise ConnectionFailed(f"failed to send request: {exc}",
                                       request=prepared) from exc
        else:  # pragma: no cover - defensive
            raise ConnectionFailed("could not send request", request=prepared)

        elapsed = time.monotonic() - started
        headers_out = CaseInsensitiveDict()
        for name, value in raw.getheaders():
            if name in headers_out:
                headers_out[name] = f"{headers_out[name]}, {value}"
            else:
                headers_out[name] = value

        with self._cookie_lock:
            try:
                jar.extract_cookies(_CookieResponseAdapter(raw),
                                    _CookieRequestAdapter(prepared))
            except Exception:  # pragma: no cover - malformed Set-Cookie
                logger.debug("failed to parse Set-Cookie", exc_info=True)

        live_connection = connection

        def _release(reusable: bool) -> None:
            if reusable:
                self._pool.release(key, live_connection)
            else:
                _safe_close(live_connection)

        response = Response(
            status_code=raw.status,
            reason=raw.reason or "",
            headers=headers_out,
            url=prepared.url,
            request=prepared,
            raw=raw,
            cookies=jar,
            elapsed=elapsed,
            release_cb=_release,
            stream=stream,
        )
        logger.debug("%s %s -> %d (%.3fs, reused=%s)", prepared.method,
                     prepared.url, raw.status, elapsed, reused)

        if not stream:
            response.read()  # fully buffer, then hand the socket back to the pool
        return response

    def _open(self, url: _URL, proxy: Optional[_Proxy], timeout: Timeout,
              verify: Union[bool, str], cert: Any) -> HTTPConnection:
        """Create and connect a socket, applying connect/read timeouts."""
        connect_timeout = timeout.connect
        try:
            if proxy is not None:
                if url.scheme == "https":
                    if proxy.scheme == "https":
                        raise ProxyError(
                            "TLS-to-the-proxy (https:// proxy URL) is not supported by "
                            "http.client; use an http:// proxy URL — the tunnel to the "
                            "target is still end-to-end encrypted via CONNECT."
                        )
                    # plain TCP to the proxy, CONNECT, then TLS to the real host
                    connection: HTTPConnection = HTTPSConnection(
                        proxy.host, proxy.port, timeout=connect_timeout,
                        context=_build_ssl_context(verify, cert))
                    connection.set_tunnel(
                        url.host, url.port,
                        headers={"Proxy-Authorization": proxy.auth_header}
                        if proxy.auth_header else {})
                else:
                    connection = HTTPConnection(proxy.host, proxy.port,
                                                timeout=connect_timeout)
            elif url.scheme == "https":
                connection = HTTPSConnection(
                    url.host, url.port, timeout=connect_timeout,
                    context=_build_ssl_context(verify, cert))
            else:
                connection = HTTPConnection(url.host, url.port, timeout=connect_timeout)

            connection.connect()
        except (socket.timeout, TimeoutError) as exc:
            raise ConnectTimeout(
                f"could not connect to {url.host}:{url.port} within "
                f"{connect_timeout}s", request=None) from exc
        except ssl.SSLCertVerificationError as exc:
            raise SSLCertError(
                f"certificate verification failed for {url.host}: {exc}. "
                f"Pass verify='/path/to/ca.pem' or verify=False (unsafe)."
            ) from exc
        except ssl.SSLError as exc:
            raise SSLCertError(f"TLS handshake failed with {url.host}: {exc}") from exc
        except socket.gaierror as exc:
            raise ConnectionFailed(f"DNS lookup failed for {url.host}: {exc}") from exc
        except OSError as exc:
            if proxy is not None:
                raise ProxyError(f"proxy {proxy.key} unreachable: {exc}") from exc
            raise ConnectionFailed(f"cannot connect to {url.host}:{url.port}: {exc}") from exc

        # switch from the connect deadline to the (usually longer) read deadline
        _apply_read_timeout(connection, timeout.read)
        if connection.sock is not None:
            try:
                connection.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:  # pragma: no cover
                pass
        return connection

    # -- cookies ---------------------------------------------------------- #

    def _apply_cookies(self, prepared: PreparedRequest, jar: CookieJar) -> None:
        with self._cookie_lock:
            try:
                jar.add_cookie_header(_CookieRequestAdapter(prepared))
            except Exception:  # pragma: no cover
                logger.debug("failed to attach cookies", exc_info=True)

    def __repr__(self) -> str:
        return (f"<Session base_url={self.base_url!r} "
                f"idle_connections={self._pool.idle_count}>")


def _clone_jar(jar: CookieJar) -> CookieJar:
    clone = CookieJar()
    for cookie in jar:
        clone.set_cookie(cookie)
    return clone


def _as_pairs(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        return list(value.items())
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return list(parse_qsl(value, keep_blank_values=True))
    return [tuple(item) for item in value]


def _merge_params(base: Any, extra: Any) -> Any:
    """Session-level params + per-request params (per-request wins on conflict)."""
    if base is None:
        return extra
    if extra is None:
        return base
    right = _as_pairs(extra)
    overridden = {key for key, _ in right}
    return [pair for pair in _as_pairs(base) if pair[0] not in overridden] + right


def _drain(response: Response) -> None:
    """Read a body we do not need so the socket can go back to the pool."""
    if response._content is not None or response._consumed:
        response.close()
        return
    total = 0
    try:
        for chunk in response.iter_raw(32768):
            total += len(chunk)
            if total > MAX_DRAIN_BYTES:
                response._release(False)
                return
    except RequestError:
        response._release(False)
    finally:
        response.close()


# --------------------------------------------------------------------------- #
# module-level API
# --------------------------------------------------------------------------- #


def request(method: str, url: str, **kwargs: Any) -> Response:
    """One-shot request.

    Connections are still pooled globally (fast), but cookies are not shared
    between calls. For login flows or many calls to the same host use
    :class:`Session`.
    """
    session_kwargs = {
        key: kwargs.pop(key) for key in
        ("trust_env", "base_url", "url_guard") if key in kwargs
    }
    with Session(pool=_GLOBAL_POOL, **session_kwargs) as session:
        return session.request(method, url, **kwargs)


def get(url: str, **kwargs: Any) -> Response:
    return request("GET", url, **kwargs)


def options(url: str, **kwargs: Any) -> Response:
    return request("OPTIONS", url, **kwargs)


def head(url: str, **kwargs: Any) -> Response:
    kwargs.setdefault("allow_redirects", False)
    return request("HEAD", url, **kwargs)


def post(url: str, **kwargs: Any) -> Response:
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any) -> Response:
    return request("PUT", url, **kwargs)


def patch(url: str, **kwargs: Any) -> Response:
    return request("PATCH", url, **kwargs)


def delete(url: str, **kwargs: Any) -> Response:
    return request("DELETE", url, **kwargs)


if __name__ == "__main__":  # pragma: no cover - tiny CLI for smoke testing
    import argparse

    parser = argparse.ArgumentParser(description="requests — stdlib HTTP client")
    parser.add_argument("url")
    parser.add_argument("-X", "--method", default="GET")
    parser.add_argument("-H", "--header", action="append", default=[])
    parser.add_argument("-d", "--data")
    parser.add_argument("-j", "--json", dest="json_body")
    parser.add_argument("-k", "--insecure", action="store_true")
    parser.add_argument("-i", "--include", action="store_true",
                        help="print response headers too")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format="%(levelname)s %(name)s %(message)s")

    cli_headers = {}
    for item in args.header:
        name, _, value = item.partition(":")
        cli_headers[name.strip()] = value.strip()

    reply = request(
        args.method, args.url,
        headers=cli_headers,
        data=args.data,
        json=_jsonlib.loads(args.json_body) if args.json_body else None,
        verify=not args.insecure,
    )
    if args.include:
        print(f"HTTP {reply.status_code} {reply.reason}")
        for name, value in reply.headers.items():
            print(f"{name}: {value}")
        print()
    print(reply.text)
