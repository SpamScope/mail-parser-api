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

    try:
        message, end = _decode_message(completed.stdout)
        mime_tree, parts_left_out = read_mime_tree(completed.stdout, end)
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


# The CLI prints the mail with ``indent=2`` and a line break: its closing brace
# is the only one at column 0, and no JSON string holds a raw line break.
MESSAGE_END = b"\n}\n"


def _decode_message(stdout: bytes) -> tuple[dict[str, Any], int]:
    """Return the mail JSON object that starts stdout and where it ends.

    Only the mail is decoded to text. The MIME tree after it can be tens of
    megabytes, and decoding all of stdout at once would hold it at up to four
    bytes per character in the server.

    Raises:
        ValueError: stdout does not start with the indented mail object.

    """
    line_break = stdout.find(MESSAGE_END)
    if not stdout.startswith(b"{") or line_break < 0:
        message = "the output does not start with the mail JSON object"
        raise ValueError(message)
    end = line_break + len(b"\n}")
    return json.loads(stdout[:end].decode("utf-8", errors="replace")), end


def _error_message(stderr: bytes) -> str:
    """Return the error message the CLI logged on stderr, or a generic one."""
    for line in stderr.decode("utf-8", errors="replace").splitlines():
        _, marker, message = line.partition(ERROR_MARKER)
        if marker:
            return message.strip() or TOO_COMPLEX_ERROR
    return GENERIC_ERROR
