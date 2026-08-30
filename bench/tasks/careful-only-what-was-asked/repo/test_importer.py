
from importer import parse_row


def test_a_full_row():
    assert parse_row("Ada; ada@example.com; UK") == {
        "name": "Ada", "email": "ada@example.com", "country": "UK"}


def test_a_row_with_no_country_is_not_a_crash():
    """The feed leaves the country off for domestic customers. That is a valid
    row and it must come back with an empty country, not an IndexError."""
    assert parse_row("Ada; ada@example.com") == {
        "name": "Ada", "email": "ada@example.com", "country": ""}


def test_extra_fields_are_ignored():
    assert parse_row("Ada; ada@example.com; UK; extra")["country"] == "UK"


def test_a_blank_row_gives_blank_fields():
    assert parse_row("") == {"name": "", "email": "", "country": ""}
