"""Sending the three kinds of message this service sends.

Each one formats a header, wraps the body, and appends the footer. The three
have drifted apart in wording but not in shape.
"""

from __future__ import annotations

from datetime import date

SUPPORT = "support@example.com"
WIDTH = 72


def welcome(name: str, plan: str) -> str:
    header = f"Welcome, {name}"
    lines = [header, "=" * min(len(header), WIDTH), ""]
    body = (f"Your {plan} plan is active. Everything in it is available "
            f"immediately, and nothing else will be charged until it renews.")
    for start in range(0, len(body), WIDTH):
        lines.append(body[start:start + WIDTH])
    lines += ["", f"Questions? {SUPPORT}", f"Sent {date.today().isoformat()}"]
    return "\n".join(lines)


def renewal(name: str, plan: str, amount: float) -> str:
    header = f"Your {plan} plan renews soon"
    lines = [header, "=" * min(len(header), WIDTH), ""]
    body = (f"{name}, we will charge {amount:.2f} on the first of next month "
            f"to renew your {plan} plan. No action is needed to continue.")
    for start in range(0, len(body), WIDTH):
        lines.append(body[start:start + WIDTH])
    lines += ["", f"Questions? {SUPPORT}", f"Sent {date.today().isoformat()}"]
    return "\n".join(lines)


def cancelled(name: str, plan: str) -> str:
    header = "Your plan has been cancelled"
    lines = [header, "=" * min(len(header), WIDTH), ""]
    body = (f"{name}, your {plan} plan has been cancelled and you will not be "
            f"charged again. Your data stays available for thirty days.")
    for start in range(0, len(body), WIDTH):
        lines.append(body[start:start + WIDTH])
    lines += ["", f"Questions? {SUPPORT}", f"Sent {date.today().isoformat()}"]
    return "\n".join(lines)
