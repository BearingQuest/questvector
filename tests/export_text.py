"""Read the text of an exported PDF or DOCX bundle, for tests.

One way to read export text, shared by every test that checks what a bundle
shows (or doesn't show).
"""

from __future__ import annotations

import base64
import re
import zipfile
import zlib
from pathlib import Path


def _decode_pdf_stream(data: bytes) -> bytes:
    """Undo ReportLab's stream filters: ASCII85 (ending in ``~>``) then Flate."""
    data = data.strip()
    if data.endswith(b"~>"):
        data = base64.a85decode(data[:-2].removeprefix(b"<~"))
    return zlib.decompress(data)


def pdf_text(path: Path) -> str:
    """Return a PDF's raw bytes plus every stream, decoded."""
    raw = path.read_bytes()
    parts = [raw.decode("latin-1")]
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            parts.append(_decode_pdf_stream(match.group(1)).decode("latin-1"))
        except zlib.error, ValueError:
            continue  # a stream with another filter (none in ReportLab's text output)
    return "\n".join(parts)


def docx_text(path: Path) -> str:
    """Return the text of every part inside a DOCX (zip) file."""
    with zipfile.ZipFile(path) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", "replace") for name in archive.namelist()
        )
