"""Talking to the pricing service.

One request per call, no batching and no throttling. Everything about the
connection is configured in `settings.py`.
"""

from __future__ import annotations

import json
import urllib.request


class PricingError(Exception):
    """The service said no."""


class Client:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                return json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as refused:
            raise PricingError(f"{refused.code} from {path}") from refused

    def price(self, sku: str) -> float:
        return float(self._get(f"/v1/price/{sku}")["amount"])

    def prices(self, skus: list[str]) -> dict[str, float]:
        """One call per SKU. The service has no batch endpoint."""
        return {sku: self.price(sku) for sku in sorted(skus)}
