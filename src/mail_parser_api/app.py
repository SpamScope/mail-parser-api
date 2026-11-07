"""FastAPI application exposing the parse service."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from importlib.metadata import version

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from mail_parser_api.parser import ParseError, ParseTimeoutError, parse_email
from mail_parser_api.rate_limit import RateLimiter, client_key

MAX_BODY_BYTES = 5 * 1024 * 1024
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_KEYS = 10_000
# Parses running at once. It bounds total child memory (2 x 192 MiB, see
# CHILD_ADDRESS_SPACE_BYTES in parser.py, plus the server) under the 512 MiB
# container limit; further requests wait for a free slot.
PARSE_CONCURRENCY = 2

RFC822_CONTENT_TYPE = "message/rfc822"
OUTLOOK_CONTENT_TYPE = "application/vnd.ms-outlook"

# Read once at startup: the version is fixed for the lifetime of the process.
MAIL_PARSER_VERSION = version("mail-parser")

access_logger = logging.getLogger("mail_parser_api.access")


def _configure_access_logger() -> None:
    """Send access log records to stderr.

    uvicorn's own access log is disabled because it includes client addresses
    and query strings; this log only has method, path, status and size.
    """
    if access_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)


def create_app() -> FastAPI:
    """Build the application with a fresh rate limiter.

    Returns:
        The FastAPI application.

    """
    _configure_access_logger()
    app = FastAPI(
        title="mail-parser-api",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    rate_limiter = RateLimiter(
        limit=RATE_LIMIT_REQUESTS,
        window=RATE_LIMIT_WINDOW_SECONDS,
        max_keys=RATE_LIMIT_MAX_KEYS,
    )
    parse_slots = asyncio.Semaphore(PARSE_CONCURRENCY)

    @app.middleware("http")
    async def log_access(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        access_logger.info(
            "%s %s %d %s",
            request.method,
            request.url.path,
            response.status_code,
            response.headers.get("content-length", "-"),
        )
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/parse")
    async def parse(request: Request) -> JSONResponse:
        peer = request.client.host if request.client else None
        key = client_key(request.headers.get("x-forwarded-for"), peer)
        if not rate_limiter.allow(key):
            raise HTTPException(status_code=429, detail="Too many requests")

        _check_content_type(request.headers.get("content-type", ""))
        raw_email = await _read_body(request)

        try:
            async with parse_slots:
                message = await asyncio.to_thread(parse_email, raw_email)
        except ParseTimeoutError as error:
            raise HTTPException(status_code=504, detail="Parsing timed out") from error
        except ParseError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        return JSONResponse(
            {"mail_parser_version": MAIL_PARSER_VERSION, "message": message}
        )

    return app


def _check_content_type(content_type: str) -> None:
    """Reject any media type other than ``message/rfc822`` with 415."""
    media_type = content_type.split(";")[0].strip().lower()
    if media_type == RFC822_CONTENT_TYPE:
        return
    if media_type == OUTLOOK_CONTENT_TYPE:
        raise HTTPException(status_code=415, detail="Outlook .msg not supported yet")
    raise HTTPException(
        status_code=415, detail=f"Content-Type must be {RFC822_CONTENT_TYPE}"
    )


async def _read_body(request: Request) -> bytes:
    """Read the request body, rejecting more than ``MAX_BODY_BYTES`` with 413.

    The declared Content-Length is checked first so that an oversized upload is
    refused before it is read; the streamed size is checked as well because the
    header can be absent or wrong.
    """
    too_large = HTTPException(status_code=413, detail="Body exceeds 5 MB")
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > MAX_BODY_BYTES:
        raise too_large

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise too_large
    return bytes(body)
