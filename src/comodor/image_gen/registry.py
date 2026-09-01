"""The one provider adapter, and the fuse.

``openai`` speaks the images API — and so does every endpoint compatible
with it, including a local image server, which is why ``base_url`` exists.
The key arrives from the environment; a counter in the brain's metadata
is the daily fuse, checked before the call and bumped after it, so an
overrun refuses in words instead of in a surprise charge.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..net.http import Session
from ..vision import sniff

TIMEOUT = (10.0, 120.0)
DAY = 86400.0

class ImageGenError(RuntimeError):
    """A refusal or a failure, in words the model can pass on."""

def _fuse_store(store: Any) -> dict[str, Any]:
    raw = store.get_meta("image_gen.usage")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(data, dict):
            return data
    return {}

def _fuse_save(store: Any, data: dict[str, Any]) -> None:
    store.set_meta("image_gen.usage", json.dumps(data))

def used_today(store: Any) -> int:
    """How many images were generated under today's date key."""
    data = _fuse_store(store)
    return int(data.get(time.strftime("%Y-%m-%d"), 0))

def check_fuse(store: Any, max_per_day: int) -> None:
    spent = used_today(store)
    if spent >= max_per_day:
        raise ImageGenError(
            f"the daily limit of {max_per_day} image(s) is used up — "
            f"{spent} generated today. Raise `image_gen.max_per_day` or "
            "wait until tomorrow; the limit exists so the bill cannot "
            "surprise anyone")

def _bump(store: Any) -> None:
    key = time.strftime("%Y-%m-%d")
    data = _fuse_store(store)
    data[key] = int(data.get(key, 0)) + 1
    # Yesterday's counts have no reader; a year of them would still be
    # smaller than one image, but the fuse should stay a fuse, not a log.
    trimmed = {name: count for name, count in data.items()
               if name >= time.strftime("%Y-%m-01")}
    _fuse_save(store, trimmed)

def generate(config: Any, store: Any, prompt: str,
             output_dir: Path, size: str = "1024x1024") -> Path:
    """One image, generated and written to disk. Returns where it went.

    ``store`` is the brain's metadata table — the fuse lives there, which
    means a delegate and the main session share one count.
    """
    settings = config.image_gen
    if not settings.enabled:
        raise ImageGenError(
            "image generation is off — enable it with "
            "`image_gen.enabled = true` in your config; it is off by "
            "default because every image costs money")
    if not prompt.strip():
        raise ImageGenError("the prompt is empty")
    check_fuse(store, int(settings.max_per_day))

    key = os.environ.get(settings.key_env, "").strip()
    if not key and not _is_local(settings):
        raise ImageGenError(
            f"the image provider's key must be in ${settings.key_env} — "
            "keys are never read from the config file")

    data = _generate_openai(settings, key, prompt, size)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = sniff(data[:8])
    suffix = ".png" if fmt == "png" else ".jpg" if fmt == "jpeg" else ""
    path = output_dir / f"gen-{int(time.time())}-{os.getpid()}{suffix}"
    path.write_bytes(data)
    _bump(store)
    return path

def _is_local(settings: Any) -> bool:
    return any(host in (settings.base_url or "")
               for host in ("localhost", "127.0.0.1"))

def _generate_openai(settings: Any, key: str, prompt: str,
                     size: str) -> bytes:
    """The OpenAI images API: POST, expect an image, or refuse in words.

    ``b64_json`` is requested over the URL form because the reply then
    arrives in the same envelope everywhere and never needs a second
    request the prompt would be repeated on.
    """
    base = (settings.base_url or "https://api.openai.com/v1").rstrip("/")
    session = Session(timeout=TIMEOUT)
    try:
        response = session.post(
            f"{base}/images/generations",
            json={"model": settings.model, "prompt": prompt,
                  "n": 1, "size": size, "response_format": "b64_json"},
            headers={"Authorization": f"Bearer {key}"},
        )
    except Exception as problem:
        raise ImageGenError(f"the image service could not be reached: "
                            f"{problem}") from None
    if not response.ok:
        detail = ""
        try:
            detail = str(response.json().get("error", {}).get("message", ""))
        except Exception:
            detail = response.text[:200]
        raise ImageGenError(f"the image service refused "
                            f"({response.status_code}): {detail}")
    try:
        payload = response.json()
        encoded = payload["data"][0].get("b64_json")
    except Exception:
        raise ImageGenError("the image service's reply was not understood "
                            "— no image in it") from None
    if not encoded:
        raise ImageGenError("the image service returned no image")
    import base64

    try:
        return base64.b64decode(encoded)
    except Exception:
        raise ImageGenError("the image service's reply was not decodable") \
            from None
