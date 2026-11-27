import subprocess
import sys

import pytest

from mail_parser_api.parser import (
    GENERIC_ERROR,
    LINUX_CHILD_LIMITS,
    MAIL_PARSER_COMMAND,
    TOO_COMPLEX_ERROR,
    ParsedEmail,
    ParseError,
    parse_email,
)

TREE = b'[\n  {\n    "index": 0,\n    "parent": null\n  }\n]\n'


def completed(returncode: int, stdout: bytes, stderr: bytes = b""):
    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return run


def test_both_documents_are_returned(monkeypatch):
    stdout = b'{\n  "subject": "hi"\n}\n' + TREE
    monkeypatch.setattr(subprocess, "run", completed(0, stdout))

    assert parse_email(b"raw") == ParsedEmail(
        message={"subject": "hi"},
        mime_tree=[{"index": 0, "parent": None, "cut": []}],
        mime_tree_parts_left_out=0,
    )


def test_attachment_payloads_are_removed(monkeypatch):
    stdout = b'{"attachments": [{"filename": "a", "payload": "QQ=="}]}\n' + TREE
    monkeypatch.setattr(subprocess, "run", completed(0, stdout))

    assert parse_email(b"raw").message == {"attachments": [{"filename": "a"}]}


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(b"no json here\n", id="no-json"),
        pytest.param(b"log line\n{\n}\n" + TREE, id="text-before-the-mail"),
        pytest.param(b"{\n  trunc", id="truncated-mail"),
        pytest.param(b'{\n  "subject": "hi"\n}\n', id="missing-tree"),
        pytest.param(b'{\n}\n[\n  {\n    "index": 0', id="truncated-tree"),
        pytest.param(b"{\n}\n{\n}\n", id="tree-not-an-array"),
    ],
)
def test_output_without_both_documents_is_a_parse_error(monkeypatch, stdout):
    monkeypatch.setattr(subprocess, "run", completed(0, stdout))

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_failure_reports_the_error_logged_on_stderr(monkeypatch):
    stderr = (
        b"2026-01-01 00:00:00,000 | mailparser | __main__ | main | 235 | ERROR "
        b"| An error occurred: boom\nTraceback (most recent call last):\n"
    )
    # 4.12.0 prints the mail before it fails on the tree; it is not used.
    monkeypatch.setattr(subprocess, "run", completed(1, b"{\n}\n", stderr))

    with pytest.raises(ParseError, match=r"^boom$"):
        parse_email(b"raw")


def test_failure_without_error_line_uses_generic_message(monkeypatch):
    monkeypatch.setattr(subprocess, "run", completed(1, b"", b"Traceback\n"))

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_failure_with_empty_error_message_is_too_complex(monkeypatch):
    # A MemoryError has no text, so the CLI logs an empty error message.
    stderr = b"2026-01-01 | mailparser | ERROR | An error occurred: \nTraceback\n"
    monkeypatch.setattr(subprocess, "run", completed(1, b"{\n}\n", stderr))

    with pytest.raises(ParseError, match=TOO_COMPLEX_ERROR):
        parse_email(b"raw")


def test_error_line_on_stdout_is_not_read(monkeypatch):
    stdout = b"2026-01-01 | mailparser | ERROR | An error occurred: boom\n"
    monkeypatch.setattr(subprocess, "run", completed(1, stdout))

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_killed_child_is_too_complex(monkeypatch):
    monkeypatch.setattr(subprocess, "run", completed(-9, b""))

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
def test_child_limits_wrap_the_command_only_on_linux(monkeypatch, platform, expected):
    calls = []

    def record(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=b"{\n}\n" + TREE, stderr=b""
        )

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "run", record)
    parse_email(b"raw")

    assert calls == [expected]
