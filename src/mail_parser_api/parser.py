"""Run the mail-parser CLI in a subprocess and shape its JSON output."""

import json
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from mail_parser_api.mime_tree import read_mime_tree

PARSE_TIMEOUT_SECONDS = 10

# Address-space cap of one parse. Real emails up to 5 MB stay well below it;
# header-heavy ones that would grow past it fail with MemoryError instead.
CHILD_ADDRESS_SPACE_BYTES = 192 * 1024 * 1024

# The installed mail-parser CLI, run with the same interpreter as the service.
# It prints the mail, then the MIME tree, as two JSON documents on stdout; its
# log lines go to stderr, and ``--log-level ERROR`` keeps only the errors.
MAIL_PARSER_COMMAND = (
    sys.executable,
    "-m",
    "mailparser",
    "--stdin",
    "--json",
    "--mime-tree",
    "--log-level",
    "ERROR",
)

# On Linux (the container) util-linux tools set the child limits before exec:
# ``choom`` makes the kernel kill the child, never uvicorn (PID 1), when memory
# runs out, and ``prlimit`` caps the memory of one parse. ``preexec_fn`` is
# avoided because the parse runs in a worker thread. macOS has neither tool.
LINUX_CHILD_LIMITS = (
    "choom",
    "-n",
    "1000",
    "--",
    "prlimit",
    f"--as={CHILD_ADDRESS_SPACE_BYTES}",
    "--",
)

# Prefix of the line the CLI logs on stderr when parsing fails.
ERROR_MARKER = "An error occurred: "
GENERIC_ERROR = "mail-parser could not parse the email"
# The child was killed by the kernel or logged a MemoryError, which has no text.
TOO_COMPLEX_ERROR = "email too complex to parse within the service limits"


@dataclass(frozen=True)
class ParsedEmail:
    """The two documents the CLI prints for one email, shaped for the response.

    Attributes:
        message: The mail-parser JSON of the email without attachment payloads.
        mime_tree: The kept entries of the MIME tree, each with ``cut``.
        mime_tree_parts_left_out: The entries of the MIME tree not kept.

    """

    message: dict[str, Any]
    mime_tree: list[dict[str, Any]]
    mime_tree_parts_left_out: int


class ParseError(Exception):
    """mail-parser failed to parse the email."""


class ParseTimeoutError(Exception):
    """mail-parser did not finish within the timeout."""


def parse_email(raw_email: bytes) -> ParsedEmail:
    """Parse a raw email with the mail-parser CLI.

    The email is passed on stdin, never through a shell. Attachment payloads are
    removed from the message; their metadata is kept. The MIME tree is bounded
    as :func:`mail_parser_api.mime_tree.read_mime_tree` describes.

    Args:
        raw_email: The raw email bytes.

    Returns:
        The message and the MIME tree of the email.

    Raises:
        ParseError: mail-parser exited with an error or did not print both
            JSON documents.
        ParseTimeoutError: mail-parser ran longer than the timeout and was killed.

    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, email on stdin
            _command(),
            input=raw_email,
            capture_output=True,
            timeout=PARSE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ParseTimeoutError from error

    if completed.returncode == -signal.SIGKILL:
        raise ParseError(TOO_COMPLEX_ERROR)
    if completed.returncode != 0:
        raise ParseError(_error_message(completed.stderr))

    stdout = completed.stdout.decode("utf-8", errors="replace")
    try:
        message, end = _decode_message(stdout)
        mime_tree, parts_left_out = read_mime_tree(stdout, end)
    except ValueError as error:
        raise ParseError(GENERIC_ERROR) from error
    for attachment in message.get("attachments", []):
        attachment.pop("payload", None)
    return ParsedEmail(message, mime_tree, parts_left_out)


def _command() -> tuple[str, ...]:
    """Return the CLI command, wrapped in the child limits on Linux."""
    if sys.platform == "linux":
        return (*LINUX_CHILD_LIMITS, *MAIL_PARSER_COMMAND)
    return MAIL_PARSER_COMMAND


def _decode_message(stdout: str) -> tuple[dict[str, Any], int]:
    """Return the mail JSON object that starts stdout and where it ends.

    It is decoded in place, without copying the output, to keep the memory of
    large results low.

    Raises:
        ValueError: stdout does not start with a JSON object.

    """
    if not stdout.startswith("{"):
        message = "the output does not start with a JSON object"
        raise ValueError(message)
    return json.JSONDecoder().raw_decode(stdout)


def _error_message(stderr: bytes) -> str:
    """Return the error message the CLI logged on stderr, or a generic one."""
    for line in stderr.decode("utf-8", errors="replace").splitlines():
        _, marker, message = line.partition(ERROR_MARKER)
        if marker:
            return message.strip() or TOO_COMPLEX_ERROR
    return GENERIC_ERROR
