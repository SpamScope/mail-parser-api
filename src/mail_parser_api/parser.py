"""Run the mail-parser CLI in a subprocess and shape its JSON output."""

import json
import subprocess
import sys
from typing import Any

PARSE_TIMEOUT_SECONDS = 10

# The installed mail-parser CLI, run with the same interpreter as the service.
# ``-l ERROR`` keeps warnings off stdout; error lines may still precede the JSON.
MAIL_PARSER_COMMAND = (
    sys.executable,
    "-m",
    "mailparser",
    "--stdin",
    "--json",
    "--log-level",
    "ERROR",
)

# Prefix of the line the CLI logs on stdout when parsing fails.
ERROR_MARKER = "An error occurred: "
GENERIC_ERROR = "mail-parser could not parse the email"


class ParseError(Exception):
    """mail-parser failed to parse the email."""


class ParseTimeoutError(Exception):
    """mail-parser did not finish within the timeout."""


def parse_email(raw_email: bytes) -> dict[str, Any]:
    """Parse a raw email with the mail-parser CLI.

    The email is passed on stdin, never through a shell. Attachment payloads are
    removed from the result; their metadata is kept.

    Args:
        raw_email: The raw email bytes.

    Returns:
        The mail-parser JSON of the email without attachment payloads.

    Raises:
        ParseError: mail-parser exited with an error or printed no JSON.
        ParseTimeoutError: mail-parser ran longer than the timeout and was killed.

    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, email on stdin
            MAIL_PARSER_COMMAND,
            input=raw_email,
            capture_output=True,
            timeout=PARSE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ParseTimeoutError from error

    stdout = completed.stdout.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise ParseError(_error_message(stdout))

    message = _extract_json(stdout)
    for attachment in message.get("attachments", []):
        attachment.pop("payload", None)
    return message


def _extract_json(stdout: str) -> dict[str, Any]:
    """Return the JSON object printed by the CLI.

    Log lines start with a timestamp; the JSON object is printed with indent=2,
    so it is the first line made of a lone ``{``.
    """
    lines = stdout.splitlines(keepends=True)
    try:
        start = lines.index("{\n")
        return json.loads("".join(lines[start:]))
    except ValueError as error:
        raise ParseError(GENERIC_ERROR) from error


def _error_message(stdout: str) -> str:
    """Return the error message logged by the CLI, or a generic one."""
    for line in stdout.splitlines():
        _, marker, message = line.partition(ERROR_MARKER)
        if marker:
            return message.strip() or GENERIC_ERROR
    return GENERIC_ERROR
