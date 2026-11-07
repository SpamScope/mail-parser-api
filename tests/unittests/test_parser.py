import subprocess
import sys

import pytest

from mail_parser_api.parser import (
    GENERIC_ERROR,
    LINUX_CHILD_LIMITS,
    MAIL_PARSER_COMMAND,
    TOO_COMPLEX_ERROR,
    ParseError,
    parse_email,
)


def completed(returncode: int, stdout: bytes):
    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout
        )

    return run


def test_log_lines_before_json_are_skipped(monkeypatch):
    stdout = b'2026-01-01 | mailparser | ERROR | Failed\n{\n  "subject": "hi"\n}\n'
    monkeypatch.setattr(subprocess, "run", completed(0, stdout))

    assert parse_email(b"raw") == {"subject": "hi"}


def test_output_without_json_is_a_parse_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", completed(0, b"no json here\n"))

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_failure_without_error_line_uses_generic_message(monkeypatch):
    monkeypatch.setattr(subprocess, "run", completed(1, b""))

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


def test_failure_with_empty_error_message_is_too_complex(monkeypatch):
    # A MemoryError has no text, so the CLI logs an empty error message.
    stdout = b"2026-01-01 | mailparser | ERROR | An error occurred: \nTraceback\n"
    monkeypatch.setattr(subprocess, "run", completed(1, stdout))

    with pytest.raises(ParseError, match=TOO_COMPLEX_ERROR):
        parse_email(b"raw")


def test_json_at_start_is_parsed_and_trailing_output_ignored(monkeypatch):
    stdout = b'{\n  "subject": "hi"\n}\ntrailer\n'
    monkeypatch.setattr(subprocess, "run", completed(0, stdout))

    assert parse_email(b"raw") == {"subject": "hi"}


def test_log_line_ending_with_a_brace_is_skipped(monkeypatch):
    stdout = b'2026-01-01 | ERROR | bad {\n{\n  "subject": "hi"\n}\n'
    monkeypatch.setattr(subprocess, "run", completed(0, stdout))

    assert parse_email(b"raw") == {"subject": "hi"}


def test_truncated_json_is_a_parse_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", completed(0, b"log\n{\n  trunc"))

    with pytest.raises(ParseError, match=GENERIC_ERROR):
        parse_email(b"raw")


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
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"{\n}\n")

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "run", record)
    parse_email(b"raw")

    assert calls == [expected]
