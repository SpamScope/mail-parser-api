# 01: Return the MIME tree beside the message

Status: ready-for-agent

**What to build:** `POST /api/parse` returns two new keys, `mime_tree` and
`mime_tree_parts_left_out`, as the [spec](../spec.md) defines them. The CLI
command gains `--mime-tree`; `parser.py` decodes the second JSON document
printed after the mail and `app.py` returns it. `message` is unchanged.

**Blocked by:** nothing. mail-parser 4.12.0 has the `--mime-tree` flag; this
ticket raises the requirement to `mail-parser[outlook]>=4.12.0`, which also
brings the security fixes made since 4.11.0.

**Context:**

- `MAIL_PARSER_COMMAND` in `src/mail_parser_api/parser.py` is the fixed
  argument list; `_extract_json()` finds the first document and decodes it
  with `raw_decode`, which also returns where it ends. The second document
  starts on the next line.
- `parse_email()` returns one dict today. It returns a `ParsedEmail` with
  `message`, `mime_tree` and `mime_tree_parts_left_out`.
- The cut lives in a module of its own, `src/mail_parser_api/mime_tree.py`,
  tested without a subprocess. It decodes the entries of the array one at a
  time and keeps only those inside the bounds.
- 4.12.0 logs to stderr: `_error_message()` reads the `An error occurred:`
  line from stderr, and stdout must start with `{`. Without this, every
  `422` after the bump carries the generic error.
- `pyproject.toml` requires `mail-parser[outlook]>=4.11.0`; that version
  rejects the new flag.

**Decided:**

- How a cut tree is reported (500 entries, 1024 characters per value,
  262,144 characters of text in all, `mime_tree_parts_left_out` and
  `cut`): see "How a cut tree is reported" in the spec.
- Failing above about 70,000 parts is acceptable; the service counts no
  parts of its own (owner, 2026-11-27). The measurements are under
  "Measurements" in the spec: 68,000 tiny parts, 88,000 empty parts and
  970 levels of nesting pass, a 5 MiB email of base64 attachments passes
  at the same peak as `--json` alone.

**Acceptance:**

- [ ] `mail_test_10` returns `200`, an unchanged `message` and nine
  `mime_tree` entries linked to the four attachments.
- [ ] Output with a missing or undecodable second document returns `422`.
- [ ] A tree of 600 entries returns 500 and
  `mime_tree_parts_left_out == 100`; a file name of 5,000 characters
  returns 1024 of them and `cut == ["filename"]`; entries past 262,144
  characters of text are left out and counted.
- [ ] A failing CLI's `An error occurred:` line on stderr becomes the
  `422` detail.
- [x] Measurements for the many-parts and the deeply-nested email recorded
  in the spec, with the decision they led to.
- [ ] `pyproject.toml`, `uv.lock` and the README contract updated.
- [ ] `make pre-commit` and `make test-cov` pass.
