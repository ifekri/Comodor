"""A key pair per connection, so a token cannot be minted by anybody else.

The first version of the Worker's `/token` took an installation id and minted
against it. Installation ids are small integers that appear in URLs; knowing
one was enough to obtain a working GitHub token for somebody else's
repositories. This is the half of the fix that lives on the agent.

Each connection gets an ECDSA P-256 key pair, generated here, at
`comodor github connect`. The public half travels in the installation flow; the
private half never leaves this machine. The Worker's grant names the public
key, and every later request is signed — so the Worker can tell one agent from
another with nothing stored on either side.

**Why the curve arithmetic is written out rather than imported.** `pip install
comodor` pulls in `rich` and nothing else, and `pyproject.toml` says so as a
promise rather than an accident. `cryptography` is a compiled dependency with a
build chain; adding it for one signature would be the second dependency and the
first one that can fail to install.

What is written out is *signing only*, and that is the part where writing it
out is defensible:

* **Verification is not here.** The Worker verifies, with Web Crypto — an
  audited implementation in the runtime. A verification bug is where forgery
  lives, and none of that code is ours.
* **The key being protected is the user's own, on the user's own machine.** The
  classic risk in a hand-written implementation is a timing side channel in the
  scalar multiplication. Exploiting one needs an attacker measuring the signer;
  an attacker on this machine already has the key file.
* **`k` is derived deterministically, RFC 6979.** The catastrophic ECDSA
  failure is a repeated or predictable nonce, which reveals the private key
  from two signatures. RFC 6979 removes the entropy source from the equation
  entirely: `k` is an HMAC of the message and the key, so it is unique per
  message by construction and cannot be weak because a random source was.

The scheme, the curve and the constants are public. What is secret is one
32-byte integer in a file with owner-only permissions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

# NIST P-256 (secp256r1). Public constants, from FIPS 186-4.
_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_A = 0xffffffff00000001000000000000000000000000fffffffffffffffffffffffc
_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_GX = 0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296
_GY = 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5


class IdentityError(RuntimeError):
    """A key could not be made, read, or used. Safe to show."""


# --------------------------------------------------------------------------- #
# the curve
# --------------------------------------------------------------------------- #


def _inverse(value: int, modulus: int) -> int:
    return pow(value, -1, modulus)


def _add(one: tuple[int, int] | None,
         two: tuple[int, int] | None) -> tuple[int, int] | None:
    """Point addition on P-256. None is the point at infinity."""
    if one is None:
        return two
    if two is None:
        return one

    (x1, y1), (x2, y2) = one, two
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None

    if one == two:
        slope = (3 * x1 * x1 + _A) * _inverse(2 * y1, _P) % _P
    else:
        slope = (y2 - y1) * _inverse(x2 - x1, _P) % _P

    x3 = (slope * slope - x1 - x2) % _P
    return (x3, (slope * (x1 - x3) - y1) % _P)


def _multiply(scalar: int, point: tuple[int, int]) -> tuple[int, int]:
    """Scalar multiplication, double-and-add.

    Not constant time, and deliberately so rather than by omission: see the
    module docstring. The operand is this machine's own key and the attacker
    who could measure this already has the file it is read from.
    """
    result: tuple[int, int] | None = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)      # type: ignore[assignment]
        scalar >>= 1
    if result is None:
        raise IdentityError("the scalar multiplied to infinity")
    return result


def _bits(data: bytes) -> int:
    """A hash as the integer ECDSA signs, truncated to the order's length."""
    return int.from_bytes(data, "big")


# --------------------------------------------------------------------------- #
# RFC 6979
# --------------------------------------------------------------------------- #


def _deterministic_k(private: int, digest: bytes) -> int:
    """`k`, from the key and the message. Never from a random source.

    A repeated or predictable `k` reveals the private key from two signatures —
    the failure that has broken real systems more than once. RFC 6979 makes it
    an HMAC chain over the message and the key, so it is unique per message by
    construction and cannot be weakened by a bad entropy source.
    """
    size = 32
    private_bytes = private.to_bytes(size, "big")

    v = b"\x01" * size
    k = b"\x00" * size

    k = hmac.new(k, v + b"\x00" + private_bytes + digest, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + private_bytes + digest, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()

    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = _bits(v)
        if 1 <= candidate < _N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


# --------------------------------------------------------------------------- #
# the identity
# --------------------------------------------------------------------------- #


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


@dataclass(frozen=True)
class ClientKey:
    """One connection's key pair.

    The private half is an integer and is never in a repr: a dataclass would
    print it by default, and a stack trace carrying it is the whole secret in
    a log file.
    """

    private: int
    public: str                 # raw uncompressed point, base64url

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        return f"<ClientKey {self.fingerprint[:12]}…>"

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the public point. What the grant is matched against."""
        return _b64(hashlib.sha256(_unb64(self.public)).digest())

    def sign(self, message: bytes) -> str:
        """An ECDSA signature over `message`, as the Worker expects it.

        Raw `r || s`, 32 bytes each — the form Web Crypto's `verify` takes for
        ECDSA. DER would be the other convention and is not what the runtime on
        the other side reads.
        """
        digest = hashlib.sha256(message).digest()
        z = _bits(digest)

        while True:
            k = _deterministic_k(self.private, digest)
            point = _multiply(k, (_GX, _GY))
            r = point[0] % _N
            if r == 0:
                continue
            s = (_inverse(k, _N) * (z + r * self.private)) % _N
            if s == 0:
                continue
            # The low-s form. Both are valid ECDSA and Web Crypto accepts
            # either; normalising means one message has one signature, which
            # is one fewer thing to differ between implementations.
            if s > _N // 2:
                s = _N - s
            return _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def generate() -> ClientKey:
    """A new key pair for one connection.

    `secrets` rather than `random`: this is the only place entropy matters,
    since `k` is derived. A predictable private key is the whole secret.
    """
    private = secrets.randbelow(_N - 1) + 1
    x, y = _multiply(private, (_GX, _GY))
    # Uncompressed point, as Web Crypto's `importKey('raw', ...)` reads it.
    public = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    return ClientKey(private=private, public=_b64(public))


# --------------------------------------------------------------------------- #
# keeping it
# --------------------------------------------------------------------------- #


def key_path(user_dir: Path, installation_id: int) -> Path:
    """Where one connection's private key lives.

    Beside the config rather than in it: the config is a file people read,
    paste from, and put in dotfile repositories, and a private key in there
    would go along for the ride.
    """
    return Path(user_dir) / "github" / f"{int(installation_id)}.key"


def save(user_dir: Path, installation_id: int, key: ClientKey) -> Path:
    """Write a key, readable by nobody else.

    The permissions are set before the bytes are written. Writing first and
    chmodding after leaves a window — short, but real — where the key is on
    disk world-readable.
    """
    path = key_path(user_dir, installation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass                      # Windows has no mode bits to set

    handle = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(f"{key.private:064x}\n{key.public}\n")
    except Exception:
        raise IdentityError(f"could not write {path}") from None
    return path


def load(user_dir: Path, installation_id: int) -> ClientKey:
    """Read a key back, or say plainly that the connection is unusable."""
    path = key_path(user_dir, installation_id)
    try:
        lines = path.read_text(encoding="utf-8").split()
    except OSError:
        raise IdentityError(
            f"no client key for installation {installation_id}. The "
            f"connection cannot be used; run `comodor github connect` again.") \
            from None

    if len(lines) < 2:
        raise IdentityError(f"{path} is not a client key")
    try:
        return ClientKey(private=int(lines[0], 16), public=lines[1])
    except ValueError:
        raise IdentityError(f"{path} is not a client key") from None


def forget(user_dir: Path, installation_id: int) -> None:
    """Remove a key. Never raises — disconnecting must always work."""
    try:
        key_path(user_dir, installation_id).unlink()
    except OSError:
        pass


def is_private(user_dir: Path, installation_id: int) -> bool:
    """Whether the key on disk is readable only by its owner.

    POSIX only; Windows has no equivalent mode bits and answers True. Read by
    `doctor`, so a key that became world-readable — a careless `chmod -R`, a
    copy through a permissive umask — is reported rather than trusted.
    """
    path = key_path(user_dir, installation_id)
    if os.name == "nt":
        return True
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return True                       # absent is not insecure
    return not (mode & (stat.S_IRGRP | stat.S_IROTH))
