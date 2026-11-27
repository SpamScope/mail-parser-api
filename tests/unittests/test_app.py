import json
import logging
import subprocess
from importlib.metadata import version

import pytest

from mail_parser_api import app as app_module
from mail_parser_api import parser as parser_module
from mail_parser_api.app import MAX_BODY_BYTES, RATE_LIMIT_REQUESTS
from mail_parser_api.parser import (
    MAIL_PARSER_COMMAND,
    TOO_COMPLEX_ERROR,
    ParsedEmail,
)

RFC822 = {"Content-Type": "message/rfc822"}


def test_healthz(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_parse_strips_attachment_payloads(client, read_sample):
    response = client.post(
        "/api/parse", content=read_sample("mail_test_10"), headers=RFC822
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mail_parser_version"] == version("mail-parser")
    attachments = body["message"]["attachments"]
    assert len(attachments) == 4
    assert all("payload" not in attachment for attachment in attachments)
    assert all("filename" in attachment for attachment in attachments)


def test_parse_returns_the_mime_tree_beside_an_unchanged_message(client, read_sample):
    raw_email = read_sample("mail_test_10")
    without_tree = [arg for arg in MAIL_PARSER_COMMAND if arg != "--mime-tree"]
    expected = json.loads(
        subprocess.run(  # noqa: S603 - fixed argv, sample email on stdin
            without_tree, input=raw_email, capture_output=True, check=True
        ).stdout
    )
    for attachment in expected["attachments"]:
        del attachment["payload"]

    response = client.post("/api/parse", content=raw_email, headers=RFC822)

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == expected
    tree = body["mime_tree"]
    assert [part["index"] for part in tree] == list(range(9))
    linked = [part["attachment"] for part in tree if part["attachment"] is not None]
    assert linked == [0, 1, 2, 3]
    assert all(part["cut"] == [] for part in tree)
    assert body["mime_tree_parts_left_out"] == 0


def test_email_without_mime_structure_has_one_part(client):
    response = client.post("/api/parse", content=b"Subject: x\n\nx", headers=RFC822)

    assert response.status_code == 200
    body = response.json()
    assert [part["content_type"] for part in body["mime_tree"]] == ["text/plain"]
    assert body["mime_tree_parts_left_out"] == 0


def test_deeply_nested_email_keeps_a_bounded_tree(client):
    levels = 600
    opening = "".join(
        f'--b{level}\nContent-Type: multipart/mixed; boundary="b{level + 1}"\n\n'
        for level in range(levels)
    )
    closing = "".join(f"--b{level}--\n" for level in reversed(range(levels + 1)))
    raw_email = (
        'Subject: deep\nContent-Type: multipart/mixed; boundary="b0"\n\n'
        f"{opening}--b{levels}\n\nleaf\n{closing}"
    ).encode()

    response = client.post("/api/parse", content=raw_email, headers=RFC822)

    assert response.status_code == 200
    body = response.json()
    assert len(body["mime_tree"]) == 500
    assert body["mime_tree"][-1]["depth"] == 499
    assert body["mime_tree_parts_left_out"] == levels + 2 - 500


def test_output_over_the_cap_returns_422_too_complex(client, read_sample, monkeypatch):
    # The real CLI: on macOS the cap is checked after the child exits, on
    # Linux the kernel also stops the child at the original cap.
    monkeypatch.setattr(parser_module, "CHILD_OUTPUT_BYTES", 1024)

    response = client.post(
        "/api/parse", content=read_sample("mail_test_10"), headers=RFC822
    )

    assert response.status_code == 422
    assert response.json() == {"detail": TOO_COMPLEX_ERROR}


def test_parse_accepts_content_type_parameters(client, read_sample):
    response = client.post(
        "/api/parse",
        content=read_sample("mail_test_19"),
        headers={"Content-Type": "message/rfc822; charset=utf-8"},
    )

    assert response.status_code == 200
    message = response.json()["message"]
    assert message["subject"] == "Test email with email address as display name"


def test_malformed_email_is_parsed_with_defects(client, read_sample):
    # mail-parser is tolerant: a malformed email still yields JSON, with defects.
    response = client.post(
        "/api/parse", content=read_sample("mail_malformed_2"), headers=RFC822
    )

    assert response.status_code == 200
    message = response.json()["message"]
    assert message["has_defects"] is True
    assert "StartBoundaryNotFoundDefect" in message["defects_categories"]


@pytest.mark.parametrize("content_type", ["text/plain", "application/json", ""])
def test_other_content_types_are_rejected(client, content_type):
    response = client.post(
        "/api/parse", content=b"x", headers={"Content-Type": content_type}
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Content-Type must be message/rfc822"}


def test_outlook_msg_is_rejected(client):
    response = client.post(
        "/api/parse",
        content=b"x",
        headers={"Content-Type": "application/vnd.ms-outlook"},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Outlook .msg not supported yet"}


def test_declared_oversized_body_is_rejected(client):
    response = client.post(
        "/api/parse", content=b"x" * (MAX_BODY_BYTES + 1), headers=RFC822
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Body exceeds 5 MB"}


def test_streamed_oversized_body_is_rejected(client):
    def chunks():
        chunk = b"x" * 1024 * 1024
        for _ in range(6):
            yield chunk

    # A generator body is sent chunked, without Content-Length.
    response = client.post("/api/parse", content=chunks(), headers=RFC822)

    assert response.status_code == 413


def test_parser_failure_returns_422(client, fake_cli):
    stderr = (
        b"2026-01-01 00:00:00,000 | mailparser | __main__ | main | 235 | ERROR "
        b"| An error occurred: boom\nTraceback (most recent call last):\n"
    )

    fake_cli(1, stderr=stderr)
    response = client.post("/api/parse", content=b"Subject: x\n\nx", headers=RFC822)

    assert response.status_code == 422
    assert response.json() == {"detail": "boom"}


def test_mail_without_tree_returns_422(client, fake_cli):
    fake_cli(0, b'{\n  "subject": "x"\n}\n')
    response = client.post("/api/parse", content=b"Subject: x\n\nx", headers=RFC822)

    assert response.status_code == 422


def test_killed_parser_returns_422_too_complex(client, fake_cli):
    fake_cli(-9)
    response = client.post("/api/parse", content=b"Subject: x\n\nx", headers=RFC822)

    assert response.status_code == 422
    assert response.json() == {"detail": TOO_COMPLEX_ERROR}


def test_parser_timeout_returns_504(client, monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    response = client.post("/api/parse", content=b"Subject: x\n\nx", headers=RFC822)

    assert response.status_code == 504
    assert response.json() == {"detail": "Parsing timed out"}


def test_rate_limit_per_forwarded_client(client, monkeypatch):
    monkeypatch.setattr(app_module, "parse_email", lambda _raw: ParsedEmail({}, [], 0))
    first_client = {**RFC822, "X-Forwarded-For": "198.51.100.7"}

    statuses = [
        client.post("/api/parse", content=b"x", headers=first_client).status_code
        for _ in range(RATE_LIMIT_REQUESTS + 1)
    ]
    other_client = {**RFC822, "X-Forwarded-For": "198.51.100.8"}
    other = client.post("/api/parse", content=b"x", headers=other_client)

    assert statuses == [200] * RATE_LIMIT_REQUESTS + [429]
    assert other.status_code == 200


def test_access_log_has_no_email_content(client, read_sample, caplog):
    raw_email = read_sample("mail_test_19")

    with caplog.at_level(logging.INFO, logger="mail_parser_api.access"):
        response = client.post("/api/parse", content=raw_email, headers=RFC822)

    size = response.headers["content-length"]
    assert [record.getMessage() for record in caplog.records] == [
        f"POST /api/parse 200 {size}"
    ]
