"""Tests for questvector.core.contact: the optional Contact.md (R9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from questvector.core.contact import parse_contact
from questvector.exceptions import ParseError

FIXTURE = Path(__file__).parent / "fixtures" / "resume" / "Contact.md"
MINIMAL = "Name: Jordan Example\nEmail: jordan@example.com\n"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "Contact.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_fixture_contact_parses_every_field() -> None:
    """R9: the synthetic Contact.md gives name, location, email, phone and profile links."""
    contact = parse_contact(FIXTURE)

    assert contact.name == "Jordan Example"
    assert contact.location == "Austin, TX"
    assert contact.email == "jordan.example@example.com"
    assert contact.phone == "+1 512 555 0100"
    assert contact.links == (
        ("LinkedIn", "https://www.linkedin.com/in/jordan-example"),
        ("GitHub", "https://github.com/jordan-example"),
    )
    assert [label for label, _ in contact.fields()] == [
        "Name",
        "Email",
        "Location",
        "Phone",
        "LinkedIn",
        "GitHub",
    ]


def test_only_name_and_email_are_required_and_keys_ignore_case(tmp_path: Path) -> None:
    """R9: Name and Email are required; the rest is optional; keys are case-insensitive."""
    contact = parse_contact(write(tmp_path, "# Contact\n\nNAME: A B\nemail: a@example.com\n"))

    assert (contact.name, contact.email) == ("A B", "a@example.com")
    assert contact.location is None and contact.phone is None and contact.links == ()


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    """R9: a missing Contact.md is one clear error naming where it looked."""
    with pytest.raises(ParseError) as exc_info:
        parse_contact(tmp_path / "Contact.md")

    assert str(tmp_path / "Contact.md") in str(exc_info.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Email: a@example.com\n", "Name is required"),
        ("Name: A\n", "Email is required"),
        (MINIMAL + "Fax: 1\n", "line 3: expected 'Key: value'"),
        (MINIMAL + "just text\n", "line 3: expected 'Key: value'"),
        (MINIMAL + "Name: B\n", "line 3: Name is given twice"),
        ("Name:\nEmail: a@example.com\n", "line 1: Name has no value"),
        ("Name: A\nEmail: not-an-email\n", "line 2: Email: not a valid email address"),
        ("Name: A\nEmail: a b@example.com\n", "not a valid email address"),
        (MINIMAL + "Phone: call me\n", "line 3: Phone: a phone number has 7 to 15 digits"),
        (MINIMAL + "Phone: 12345\n", "a phone number has 7 to 15 digits"),
        (MINIMAL + "GitHub: http://github.com/x\n", "a URL must start with https://"),
        (MINIMAL + "GitHub: javascript:alert(1)\n", "a URL must start with https://"),
        (MINIMAL + "Website: https://localhost/x\n", "a URL needs a host name"),
        (MINIMAL + "Website: https://user:pw@example.com\n", "can't contain a user name"),
        (MINIMAL + "Website: https://example.com/a b\n", "can't contain spaces"),
        (MINIMAL + "Location: " + "x" * 201 + "\n", "longer than 200 characters"),
        ("Name: " + "n" * 81 + "\nEmail: a@example.com\n", "longer than 80 characters"),
        ("Name: A\x07B\nEmail: a@example.com\n", "contains a control character"),
    ],
)
def test_invalid_contact_files_name_the_line_and_the_problem(
    tmp_path: Path, text: str, expected: str
) -> None:
    """R9: each invalid field is refused with the file, line and reason."""
    with pytest.raises(ParseError, match=expected):
        parse_contact(write(tmp_path, text))


def test_a_file_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    """R9: a non-UTF-8 Contact.md is a ParseError, not a crash."""
    path = tmp_path / "Contact.md"
    path.write_bytes(b"Name: \xff\xfe\n")

    with pytest.raises(ParseError, match="as UTF-8 text"):
        parse_contact(path)
