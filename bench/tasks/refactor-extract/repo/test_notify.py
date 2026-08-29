from datetime import date

from notify import SUPPORT, cancelled, renewal, welcome


def wrapped(text: str) -> list[str]:
    return text.split("\n")


def test_welcome_names_the_plan():
    out = welcome("Ada", "growth")
    assert out.startswith("Welcome, Ada\n=")
    assert "growth plan is active" in out


def test_renewal_carries_the_amount():
    assert "12.50" in renewal("Ada", "growth", 12.5)


def test_cancellation_says_thirty_days():
    assert "thirty days" in cancelled("Ada", "growth")


def test_every_message_ends_the_same_way():
    for message in (welcome("Ada", "growth"),
                    renewal("Ada", "growth", 1.0),
                    cancelled("Ada", "growth")):
        rows = wrapped(message)
        assert rows[-2] == f"Questions? {SUPPORT}"
        assert rows[-1] == f"Sent {date.today().isoformat()}"


def test_no_line_is_wider_than_the_limit():
    for message in (welcome("Ada", "growth"),
                    renewal("Ada", "growth", 1.0),
                    cancelled("Ada", "growth")):
        assert all(len(row) <= 72 for row in wrapped(message))
