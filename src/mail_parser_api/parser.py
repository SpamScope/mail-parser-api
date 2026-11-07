"""Run the mail-parser CLI in a subprocess and shape its JSON output."""

import json
import signal
import subprocess
import sys
from typing import Any

PARSE_TIMEOUT_SECONDS = 10

# Address-space cap of one parse. Real emails up to 5 MB stay well below it;
# header-heavy ones that would grow past it fail with MemoryError instead.
CHILD_ADDRESS_SPACE_BYTES = 192 * 1024 * 1024

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

# Prefix of the line the CLI logs on stdout when parsing fails.
ERROR_MARKER = "An error occurred: "
GENERIC_ERROR = "mail-parser could not parse the email"
# The child was killed by the kernel or logged a MemoryError, which has no text.
TOO_COMPLEX_ERROR = "email too complex to parse within the service limits"


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
    stdout = completed.stdout.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise ParseError(_error_message(stdout))

    message = _extract_json(stdout)
    for attachment in message.get("attachments", []):
        attachment.pop("payload", None)
    return message


def _command() -> tuple[str, ...]:
    """Return the CLI command, wrapped in the child limits on Linux."""
    if sys.platform == "linux":
        return (*LINUX_CHILD_LIMITS, *MAIL_PARSER_COMMAND)
    return MAIL_PARSER_COMMAND


def _extract_json(stdout: str) -> dict[str, Any]:
    """Return the JSON object printed by the CLI.

    Log lines start with a timestamp; the JSON object is printed with indent=2,
    so it is the first line made of a lone ``{``. It is decoded in place, without
    copying the output, to keep the memory of large results low.
    """
    if stdout.startswith("{\n"):
        start = 0
    else:
        start = stdout.find("\n{\n") + 1
        if start == 0:
            raise ParseError(GENERIC_ERROR)
    try:
        message, _ = json.JSONDecoder().raw_decode(stdout, start)
    except ValueError as error:
        raise ParseError(GENERIC_ERROR) from error
    return message


def _error_message(stdout: str) -> str:
    """Return the error message logged by the CLI, or a generic one."""
    for line in stdout.splitlines():
        _, marker, message = line.partition(ERROR_MARKER)
        if marker:
            return message.strip() or TOO_COMPLEX_ERROR
    return GENERIC_ERROR
