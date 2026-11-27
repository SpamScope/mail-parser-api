import json
import sys
import tracemalloc

import pytest

from mail_parser_api import parser
from mail_parser_api.parser import (
    CHILD_ADDRESS_SPACE_BYTES,
    CHILD_OUTPUT_BYTES,
    GENERIC_ERROR,
    LINUX_CHILD_LIMITS,
    MAIL_PARSER_COMMAND,
    TOO_COMPLEX_ERROR,
    ParsedEmail,
    ParseError,
    parse_email,
)

TREE = b'[\n  {\n    "index": 0,\n    "parent": null\n  }\n]\n'


def test_both_documents_are_returned(fake_cli):
    stdout = b'{\n  "subject": "hi"\n}\n' + TREE
    fake_cli(0, stdout)

    assert parse_email(b"raw") == ParsedEmail(
        message={"subject": "hi"},
        mime_tree=[{"index": 0, "parent": None, "cut": []}],
        mime_tree_parts_left_out=0,
    )


def test_attachment_payloads_are_removed(fake_cli):
    mail = {"attachments": [{"filename": "a", "payload": "QQ=="}]}
    stdout = json.dumps(mail, indent=2).encode() + b"\n" + TREE
    fake_cli(0, stdout)

    assert parse_email(b"raw").message == {"attachments": [{"filename": "a"}]}


def test_large_tree_with_a_non_bmp_character_is_not_decoded_whole(fake_cli):
    # One character outside the BMP would make a str of all of stdout take
    # four bytes per character: about six times stdout, in the server.
    entries = [
        {"index": index, "filename": "\U0001f600" if index == 0 else "a" * 100}
        for index in range(50_000)
    ]
    tree = json.dumps(entries, ensure_ascii=False, indent=2).encode()
    stdout = b'{\n  "subject": "\xf0\x9f\x98\x80"\n}\n' + tree + b"\n"
    fake_cli(0, stdout)

    tracemalloc.start()
    try:
        parsed = parse_email(b"raw")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert parsed.mime_tree_parts_left_out == 50_000 - 500
    # stdout is read once from the output file; decoding all of it as text
    # would add four more bytes per byte.
    assert peak < 2 * len(stdout)


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(b"no json here\n", id="no-json"),
        pytest.param(b'{"subject": "hi"}\n' + TREE, id="mail-not-indented"),
        pytest.param(b"log line\n{\n}\n" + TREE, id="text-before-the-mail"),
        pytest.param(b"{\n  trunc", id="truncated-mail"),
        pytest.param(b'{\n  "subject": "hi"\n}\n', id="missing-tree"),
        pytest.param(b'{\n}\n[\n  {\n    "index": 0', id="truncated-tree"),
        pytest.param(b"{\n}\n{\n}\n", id="tree-not-an-array"),
    ],
)
def test_output_without_both_documents_is_a_parse_error(fake_cli, stdout):
    fake_cli(0, stdout)

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_failure_reports_the_error_logged_on_stderr(fake_cli):
    stderr = (
        b"2026-01-01 00:00:00,000 | mailparser | __main__ | main | 235 | ERROR "
        b"| An error occurred: boom\nTraceback (most recent call last):\n"
    )
    # 4.12.0 prints the mail before it fails on the tree; it is not used.
    fake_cli(1, b"{\n}\n", stderr)

    with pytest.raises(ParseError, match=r"^boom$"):
        parse_email(b"raw")


def test_failure_without_error_line_uses_generic_message(fake_cli):
    fake_cli(1, b"", b"Traceback\n")

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_failure_with_empty_error_message_is_too_complex(fake_cli):
    # A MemoryError has no text, so the CLI logs an empty error message.
    stderr = b"2026-01-01 | mailparser | ERROR | An error occurred: \nTraceback\n"
    fake_cli(1, b"{\n}\n", stderr)

    with pytest.raises(ParseError, match=TOO_COMPLEX_ERROR):
        parse_email(b"raw")


def test_error_line_on_stdout_is_not_read(fake_cli):
    stdout = b"2026-01-01 | mailparser | ERROR | An error occurred: boom\n"
    fake_cli(1, stdout)

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_killed_child_is_too_complex(fake_cli):
    fake_cli(-9, b"")

    with pytest.raises(ParseError, match=TOO_COMPLEX_ERROR):
        parse_email(b"raw")


def test_command_asks_for_the_mime_tree():
    assert "--mime-tree" in MAIL_PARSER_COMMAND


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", (*LINUX_CHILD_LIMITS, *MAIL_PARSER_COMMAND)),
        ("darwin", MAIL_PARSER_COMMAND),
    ],
)
def test_child_limits_wrap_the_command_only_on_linux(
    fake_cli, monkeypatch, platform, expected
):
    calls = fake_cli(0, b"{\n}\n" + TREE)
    monkeypatch.setattr(sys, "platform", platform)

    parse_email(b"raw")

    assert calls == [expected]


def test_linux_limits_cap_memory_and_output():
    assert f"--as={CHILD_ADDRESS_SPACE_BYTES}" in LINUX_CHILD_LIMITS
    assert f"--fsize={CHILD_OUTPUT_BYTES}" in LINUX_CHILD_LIMITS


def test_output_at_the_cap_is_too_complex(fake_cli, monkeypatch):
    stdout = b"{\n}\n" + TREE
    monkeypatch.setattr(parser, "CHILD_OUTPUT_BYTES", len(stdout))
    # On Linux the kernel stops the child there and the CLI exits with 1.
    fake_cli(1, stdout, b"An error occurred: [Errno 27] File too large\n")

    with pytest.raises(ParseError, match=TOO_COMPLEX_ERROR):
        parse_email(b"raw")


def test_output_below_the_cap_is_parsed(fake_cli, monkeypatch):
    stdout = b"{\n}\n" + TREE
    monkeypatch.setattr(parser, "CHILD_OUTPUT_BYTES", len(stdout) + 1)
    fake_cli(0, stdout)

    assert parse_email(b"raw").mime_tree_parts_left_out == 0
