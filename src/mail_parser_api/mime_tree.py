"""Read the MIME tree printed by the mail-parser CLI and bound it.

The bounds are those of MailXRay, so that the live parser page and MailXRay
read one shape: the first entries are kept, every string value is cut, and
the text of the kept entries is bounded as a whole. Nothing is dropped
silently: a cut value is named in ``cut`` and a part left out is counted.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

MAX_MIME_TREE_PARTS = 500
"""Entries kept. Parents precede children, so the kept prefix is a tree."""

MAX_STRUCTURE_TEXT = 1024
"""Characters kept of every string value, ``embedded_headers`` included."""

MAX_MIME_TREE_TEXT = 262_144
"""Characters of text the kept entries hold together, counted after the cut.

The first entry that would exceed it and every entry after it are left out:
500 entries of eleven values of 1024 characters would otherwise hold 5.6
million characters, and a control character takes six bytes in JSON.
"""

_NOT_WHITESPACE = re.compile(r"[^ \t\n\r]")


def read_mime_tree(text: str, start: int) -> tuple[list[dict[str, Any]], int]:
    """Decode the JSON array of the MIME tree and keep its bounded prefix.

    Entries are decoded one at a time: those past the bounds are counted and
    dropped as soon as they are decoded, so the memory held does not grow
    with the number of parts the sender chose.

    Args:
        text: The CLI output.
        start: Where the array may start, after optional whitespace.

    Returns:
        ``(mime_tree, mime_tree_parts_left_out)``: the kept entries, each
        with ``cut``, and the number of entries not kept.

    Raises:
        ValueError: The text at ``start`` is not a JSON array of objects.

    """
    kept: list[dict[str, Any]] = []
    left_out = 0
    characters = 0
    for entry in _entries(text, start):
        if not left_out and len(kept) < MAX_MIME_TREE_PARTS:
            part = _bounded_part(entry)
            characters += _text_length(part)
            if characters <= MAX_MIME_TREE_TEXT:
                kept.append(part)
                continue
        left_out += 1
    return kept, left_out


def _entries(text: str, start: int) -> Iterator[dict[str, Any]]:
    """Yield the objects of the JSON array at ``start``, one at a time.

    Raises:
        ValueError: The text is not a closed JSON array of objects.

    """
    decoder = json.JSONDecoder()
    position = _skip_whitespace(text, start)
    if not text.startswith("[", position):
        message = "the MIME tree is not a JSON array"
        raise ValueError(message)
    position = _skip_whitespace(text, position + 1)
    if text.startswith("]", position):
        return
    while True:
        entry, position = decoder.raw_decode(text, position)
        if not isinstance(entry, dict):
            message = "a MIME tree entry is not a JSON object"
            raise ValueError(message)  # noqa: TRY004 - malformed output, not a type
        yield entry
        position = _skip_whitespace(text, position)
        if text.startswith("]", position):
            return
        if not text.startswith(",", position):
            message = "the MIME tree array is not closed"
            raise ValueError(message)
        position = _skip_whitespace(text, position + 1)


def _skip_whitespace(text: str, position: int) -> int:
    """Return the position of the next non-whitespace character, or the end."""
    match = _NOT_WHITESPACE.search(text, position)
    return match.start() if match else len(text)


def _bounded_part(entry: dict[str, Any]) -> dict[str, Any]:
    """Return an entry with every string value cut and its ``cut`` list.

    The values of ``embedded_headers`` are cut too and named
    ``embedded_headers.<name>``. Nothing else changes: control characters
    and bidirectional overrides are evidence and stay as declared.
    """
    cut: list[str] = []
    part: dict[str, Any] = {}
    for key, value in entry.items():
        if isinstance(value, str):
            part[key] = _bounded_text(value, key, cut)
        elif key == "embedded_headers" and isinstance(value, dict):
            part[key] = {
                name: _bounded_text(text, f"{key}.{name}", cut)
                if isinstance(text, str)
                else text
                for name, text in value.items()
            }
        else:
            part[key] = value
    part["cut"] = cut
    return part


def _bounded_text(value: str, key: str, cut: list[str]) -> str:
    """Return ``value`` cut to the bound, naming ``key`` in ``cut`` if cut."""
    if len(value) <= MAX_STRUCTURE_TEXT:
        return value
    cut.append(key)
    return value[:MAX_STRUCTURE_TEXT]


def _text_length(part: dict[str, Any]) -> int:
    """Return the characters of the string values of a bounded entry."""
    headers = part.get("embedded_headers")
    values = [*part.values(), *(headers.values() if isinstance(headers, dict) else ())]
    return sum(len(value) for value in values if isinstance(value, str))
