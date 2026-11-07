import subprocess

import pytest

from mail_parser_api.parser import GENERIC_ERROR, ParseError, parse_email


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
