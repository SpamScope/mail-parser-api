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

# The CLI prints the tree with ``indent=2``: an entry of the array opens and
# closes at column 2, its nested ``embedded_headers`` closes at column 4, and
# no JSON string holds a raw line break. So this marks the end of an entry.
_ENTRY_CLOSE = b"\n  }"
_NOT_WHITESPACE = re.compile(rb"[^ \t\n\r]")


def read_mime_tree(output: bytes, start: int) -> tuple[list[dict[str, Any]], int]:
    """Decode the MIME tree the CLI printed and keep its bounded prefix.

    The output is never decoded as a whole: one non-BMP character would make
    Python store all of it at four bytes per character. Only the kept entries
    are decoded, one at a time; the others are found and counted.

    Args:
        output: The CLI stdout.
        start: Where the array may start, after optional whitespace.

    Returns:
        ``(mime_tree, mime_tree_parts_left_out)``: the kept entries, each
        with ``cut``, and the number of entries not kept.

    Raises:
        ValueError: The bytes at ``start`` are not the indented JSON array of
            objects the CLI prints.

    """
    kept: list[dict[str, Any]] = []
    left_out = 0
    characters = 0
    for begin, end in _entry_spans(output, start):
        if not left_out and len(kept) < MAX_MIME_TREE_PARTS:
            part = _bounded_part(_decode_entry(output[begin:end]))
            characters += _text_length(part)
            if characters <= MAX_MIME_TREE_TEXT:
                kept.append(part)
                continue
        left_out += 1
    return kept, left_out


def _entry_spans(output: bytes, start: int) -> Iterator[tuple[int, int]]:
    """Yield where each entry of the indented array at ``start`` begins and ends.

    Raises:
        ValueError: The bytes are not a closed, indented JSON array of objects.

    """
    position = _skip_whitespace(output, start)
    if not output.startswith(b"[", position):
        message = "the MIME tree is not a JSON array"
        raise ValueError(message)
    position = _skip_whitespace(output, position + 1)
    if output.startswith(b"]", position):
        return
    while True:
        close = output.find(_ENTRY_CLOSE, position)
        if not output.startswith(b"{", position) or close < 0:
            message = "a MIME tree entry is not an indented JSON object"
            raise ValueError(message)
        end = close + len(_ENTRY_CLOSE)
        yield position, end
        position = _skip_whitespace(output, end)
        if output.startswith(b"]", position):
            return
        if not output.startswith(b",", position):
            message = "the MIME tree array is not closed"
            raise ValueError(message)
        position = _skip_whitespace(output, position + 1)


def _skip_whitespace(output: bytes, position: int) -> int:
    """Return the position of the next non-whitespace byte, or the end."""
    match = _NOT_WHITESPACE.search(output, position)
    return match.start() if match else len(output)


def _decode_entry(entry: bytes) -> dict[str, Any]:
    """Decode one entry, whose bytes start with ``{``.

    Raises:
        ValueError: The bytes are not one complete JSON object.

    """
    return json.loads(entry.decode("utf-8", errors="replace"))


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
