"""Contact details for the resume export, read from an optional ``Contact.md``.

The file is plain ``Key: value`` lines, one per line. Blank lines and ``#`` lines are
ignored. Keys (case-insensitive): ``Name`` and ``Email`` are required; ``Location`` and
``Phone`` are optional; ``LinkedIn``, ``GitHub``, ``Website`` and ``Portfolio`` take an
https URL. An unknown or repeated key is an error, so a typo fails loudly.

Contact details stay on the machine (ADR-0032). This module is not imported by
:mod:`questvector.core.llm`, and the contact is not part of
:class:`~questvector.core.models.Dossier`, so nothing here can reach a narrative prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from questvector.exceptions import ParseError

_LINK_KEYS = {
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "website": "Website",
    "portfolio": "Portfolio",
}
_KNOWN_KEYS = {"name", "email", "location", "phone", *_LINK_KEYS}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE_CHARS_RE = re.compile(r"[0-9+()\-. ]+")
_MAX_FIELD_LEN = 200
_MAX_NAME_LEN = 80


@dataclass(frozen=True, slots=True)
class Contact:
    """Validated contact details.

    Attributes:
        name: The candidate's name.
        email: The email address (becomes a ``mailto:`` link).
        location: Optional city or region.
        phone: Optional phone number, as written.
        links: ``(label, https URL)`` pairs, in file order.
    """

    name: str
    email: str
    location: str | None = None
    phone: str | None = None
    links: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def fields(self) -> tuple[tuple[str, str], ...]:
        """Return every field as ``(label, value)``, for checks that look for each in a file."""
        items = [("Name", self.name), ("Email", self.email)]
        if self.location:
            items.append(("Location", self.location))
        if self.phone:
            items.append(("Phone", self.phone))
        items.extend(self.links)
        return tuple(items)


def _check_url(value: str) -> str | None:
    """Return why ``value`` isn't an acceptable profile URL, or ``None`` if it is."""
    if re.search(r"\s", value):
        return "a URL can't contain spaces"
    parts = urlsplit(value)
    if parts.scheme != "https":
        return "a URL must start with https://"
    if not parts.hostname or "." not in parts.hostname:
        return "a URL needs a host name such as example.com"
    if parts.username or parts.password:
        return "a URL can't contain a user name or password"
    return None


def _check_value(key: str, value: str) -> str | None:
    """Return why ``value`` is invalid for ``key`` (lowercase), or ``None`` if it's fine."""
    if len(value) > _MAX_FIELD_LEN:
        return f"longer than {_MAX_FIELD_LEN} characters"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "contains a control character"
    if key == "name" and len(value) > _MAX_NAME_LEN:
        return f"longer than {_MAX_NAME_LEN} characters"
    if key == "email" and _EMAIL_RE.fullmatch(value) is None:
        return "not a valid email address"
    if key == "phone":
        digits = sum(ch.isdigit() for ch in value)
        if _PHONE_CHARS_RE.fullmatch(value) is None or not 7 <= digits <= 15:
            return "a phone number has 7 to 15 digits and only digits, spaces and + ( ) - ."
    if key in _LINK_KEYS:
        return _check_url(value)
    return None


def parse_contact(path: Path) -> Contact:
    """Read and validate ``Contact.md``.

    Args:
        path: Path to the contact file.

    Returns:
        The validated :class:`Contact`.

    Raises:
        ParseError: If the file is missing, isn't UTF-8 text, has an unknown or repeated
            key, an invalid value, or lacks ``Name`` or ``Email``. The message names the
            file and the line or field.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ParseError(
            f"{path.name} not found at {path} (see the README for the Contact.md format)"
        ) from None
    except (UnicodeDecodeError, OSError) as exc:
        raise ParseError(f"Could not read {path.name} at {path} as UTF-8 text: {exc}") from exc

    values: dict[str, str] = {}
    links: list[tuple[str, str]] = []
    for number, line in enumerate(content.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key_text, separator, value = line.partition(":")
        key = key_text.strip().lower()
        value = value.strip()
        if not separator or key not in _KNOWN_KEYS:
            raise ParseError(
                f"{path.name} line {number}: expected 'Key: value' with a key from "
                "Name, Email, Location, Phone, LinkedIn, GitHub, Website, Portfolio"
            )
        if key in values:
            raise ParseError(f"{path.name} line {number}: {key_text.strip()} is given twice")
        if not value:
            raise ParseError(f"{path.name} line {number}: {key_text.strip()} has no value")
        problem = _check_value(key, value)
        if problem:
            raise ParseError(f"{path.name} line {number}: {key_text.strip()}: {problem}")
        values[key] = value
        if key in _LINK_KEYS:
            links.append((_LINK_KEYS[key], value))

    for required in ("name", "email"):
        if required not in values:
            raise ParseError(f"{path.name}: {required.capitalize()} is required")
    return Contact(
        name=values["name"],
        email=values["email"],
        location=values.get("location"),
        phone=values.get("phone"),
        links=tuple(links),
    )
