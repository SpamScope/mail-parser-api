# 01: Return the MIME tree beside the message

Status: needs-triage

**What to build:** `POST /api/parse` returns a third key, `mime_tree`, as
the [spec](../spec.md) defines it. The CLI command gains `--mime-tree`;
`parser.py` decodes the second JSON document printed after the mail and
`app.py` returns it. `message` is unchanged.

**Blocked by:** a mail-parser release with the `--mime-tree` flag (see
"Blocked by" in the spec). Until then the work can be done against
mail-parser's `feature/message-structure` branch, but not released.

**Context:**

- `MAIL_PARSER_COMMAND` in `src/mail_parser_api/parser.py` is the fixed
  argument list; `_extract_json()` finds the first document and decodes it
  with `raw_decode`, which also returns where it ends. The second document
  starts on the next line.
- `parse_email()` returns one dict today. Its return value has to carry
  both documents.
- `pyproject.toml` requires `mail-parser[outlook]>=4.11.0`; that version
  rejects the new flag.

**Open questions:** the two listed in the spec: a cap on the number of
entries, and the memory of measuring base64 attachments under the
192 MiB cap. Both need a measurement before the ticket is ready for an
agent.

**Acceptance:**

- [ ] `mail_test_10` returns `200`, an unchanged `message` and nine
  `mime_tree` entries linked to the four attachments.
- [ ] Output with a missing or undecodable second document returns `422`.
- [ ] Measurements for the many-parts and the deeply-nested email recorded
  in this file, with the decision they led to.
- [ ] `pyproject.toml`, `uv.lock` and the README contract updated.
- [ ] `make pre-commit` and `make test-cov` pass.
