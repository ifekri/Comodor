"""Where the pricing service is, and who we are to it."""

from __future__ import annotations

import os

BASE_URL = os.environ.get("PRICING_URL", "https://pricing.internal/api")
TOKEN = os.environ.get("PRICING_TOKEN", "")
TIMEOUT = float(os.environ.get("PRICING_TIMEOUT", "10"))
