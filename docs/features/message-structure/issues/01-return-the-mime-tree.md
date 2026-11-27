# 01: Return the MIME tree beside the message

Status: needs-triage

**What to build:** `POST /api/parse` returns a third key, `mime_tree`, as
the [spec](../spec.md) defines it. The CLI command gains `--mime-tree`;
`parser.py` decodes the second JSON document printed after the mail and
`app.py` returns it. `message` is unchanged.

**Blocked by:** nothing. mail-parser 4.12.0 has the `--mime-tree` flag; this
ticket raises the requirement to `mail-parser[outlook]>=4.12.0`, which also
brings the security fixes made since 4.11.0.

**Context:**

- `MAIL_PARSER_COMMAND` in `src/mail_parser_api/parser.py` is the fixed
  argument list; `_extract_json()` finds the first document and decodes it
  with `raw_decode`, which also returns where it ends. The second document
  starts on the next line.
- `parse_email()` returns one dict today. Its return value has to carry
  both documents.
- `pyproject.toml` requires `mail-parser[outlook]>=4.11.0`; that version
  rejects the new flag.

**Decided:** how a cut tree is reported (500 entries, 1024 characters per
value, `mime_tree_parts_left_out` and `cut`): see "How a cut tree is
reported" in the spec.

**Open questions:** the two listed in the spec: the largest tree the child
still produces under the 192 MiB cap, and the memory of measuring base64
attachments under it. Both need a measurement before the ticket is ready
for an agent.

**Acceptance:**

- [ ] `mail_test_10` returns `200`, an unchanged `message` and nine
  `mime_tree` entries linked to the four attachments.
- [ ] Output with a missing or undecodable second document returns `422`.
- [ ] A tree of 600 entries returns 500 and
  `mime_tree_parts_left_out == 100`; a file name of 5,000 characters
  returns 1024 of them and `cut == ["filename"]`.
- [ ] Measurements for the many-parts and the deeply-nested email recorded
  in this file, with the decision they led to.
- [ ] `pyproject.toml`, `uv.lock` and the README contract updated.
- [ ] `make pre-commit` and `make test-cov` pass.
