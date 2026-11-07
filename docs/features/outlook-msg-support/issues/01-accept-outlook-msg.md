# 01: Accept Outlook .msg files

Status: needs-triage

**What to build:** Let `POST /api/parse` accept Outlook `.msg` files sent with
`Content-Type: application/vnd.ms-outlook` and return the same response shape
as for a raw email (`mail_parser_version` and `message` without attachment
payloads). Today this content type is rejected with `415` and the detail
"Outlook .msg not supported yet".

**Context:**

- The image already installs `mail-parser[outlook]` (the `extract-msg` extra),
  so no new dependency is needed.
- The mail-parser CLI cannot read Outlook files from stdin
  ("You can't use stdin with msg Outlook"): it needs `--outlook --file <path>`.
  The body would have to be written to a temporary file under `/tmp`, the only
  writable path in the container (`tmpfs`), and removed after parsing.
- The same limits apply: 5 MB body, 10-second subprocess timeout, rate limit,
  no email content in logs.

**Open questions:**

- Is `application/vnd.ms-outlook` the only content type to accept, or should
  the live parser page send another one for `.msg` uploads?
- Does `extract-msg` write anything outside the temporary file that would fail
  on a read-only filesystem?

**Acceptance:**

- [ ] A sample `.msg` returns `200` with the parsed message and no attachment
  `payload`.
- [ ] The temporary file is removed after success, failure and timeout.
- [ ] README endpoint contract updated; the `415` row for Outlook removed.
