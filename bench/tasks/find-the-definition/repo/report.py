"""A monthly summary, printed for whoever asks."""

from __future__ import annotations

from app.billing import invoice_lines, invoice_total


def render(account: str, usage: dict[str, int]) -> str:
    rows = [f"{meter:14} {amount:>10.2f}"
            for meter, amount in invoice_lines(account, usage)]
    rows.append(f"{'total':14} {invoice_total(account, usage):>10.2f}")
    return "\n".join(rows)


if __name__ == "__main__":
    print(render("acme", {"requests": 25_000, "storage_gb": 42}))
