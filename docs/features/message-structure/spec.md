# Return the MIME tree of the parsed email

Branch: `feature/message-structure`. Agreed with the owner on 2026-11-22,
in the session that designed the feature in mail-parser. This file carries
everything decided there that concerns this repository, so the work can
start without that conversation.

Source of truth for the tree: `docs/features/message-structure/spec.md` and
`docs/adr/0002-mime-tree-as-flat-parent-indexed-list.md` in
[SpamScope/mail-parser](https://github.com/SpamScope/mail-parser). If this
file and that one differ, that one is right.

## Goal and boundaries

The live parser page of spamscope.ai will draw the structure of an email:
its delivery path and its MIME tree. The delivery path is already in the
response (`message.received`). This service adds the one missing piece, the
MIME tree.

- `message` does not change. Whoever reads it today reads the same thing.
- The tree is a new key beside it, `mime_tree`.
- This service does not draw anything and returns no text drawing. The
  page draws from the data.
- No change to limits, rate limiting, logging or the Outlook refusal.

## Blocked by

Nothing any more. mail-parser 4.12.0, released, has the `--mime-tree` flag
and the security fixes made since 4.11.0. `pyproject.toml` must require it
(`mail-parser[outlook]>=4.12.0`), because an older CLI rejects the flag and
every parse would fail.

## What mail-parser provides

`mailparser --stdin --json --mime-tree` prints two JSON documents, one
after the other, both indented:

1. the mail, exactly as `--json` alone prints it;
1. the MIME tree, a JSON array, starting on the line after the first
   document ends. It always has at least one entry, the root: an email
   without MIME structure, and even an empty one, has one part.

Since 4.12.0 the CLI logs to stderr, the `An error occurred:` line
included, so stdout holds nothing but the two documents (measured on
2026-11-27, see below). Before 4.12.0 log lines went to stdout and could
precede the first document; the service no longer looks for them there.

The tree is a flat array. Entry `i` describes MIME part `i`, the number
defect messages quote as `part N`, and names its enclosing part in
`parent`. Every entry has all of these keys:

| Key                         | Type          | Meaning                                                                        |
| --------------------------- | ------------- | ------------------------------------------------------------------------------ |
| `index`                     | int           | Position in the array.                                                         |
| `parent`                    | int / null    | `index` of the enclosing part; null for the root.                              |
| `depth`                     | int           | 0 for the root.                                                                |
| `content_type`              | string        | The type the parser acted on, lowercase.                                       |
| `content_type_raw`          | string / null | The literal `Content-Type` value; null when the part has none.                 |
| `content_transfer_encoding` | string / null | Declared encoding; null when absent.                                           |
| `charset`                   | string / null | Declared charset.                                                              |
| `content_disposition`       | string / null | Declared disposition type.                                                     |
| `filename`                  | string / null | Declared file name, decoded.                                                   |
| `content_id`                | string / null | Declared `Content-ID`.                                                         |
| `boundary`                  | string / null | Declared boundary of a multipart.                                              |
| `size`                      | int / null    | Octets of a leaf after transfer decoding; null for a container.                |
| `roles`                     | array         | Any of `container`, `body`, `attachment`.                                      |
| `attachment`                | int / null    | Position of the matching entry in `message.attachments`.                       |
| `defects`                   | array         | Names of the defect categories recorded against the part.                      |
| `recovered`                 | bool          | True for a part recovered from an epilogue.                                    |
| `embedded_headers`          | object / null | Literal `from`, `subject`, `date` of a message enclosed in a `message/*` part. |

The tree holds no payload, so there is nothing to strip from it.
`attachment` stays valid after this service removes `payload` from the
attachments, because entries are removed from none of them.

## Response

```json
{
  "mail_parser_version": "<version>",
  "message": {"...": "unchanged"},
  "mime_tree": [
    {"index": 0, "parent": null, "depth": 0, "content_type": "multipart/mixed", "...": "...", "cut": []},
    {"index": 1, "parent": 0, "depth": 1, "content_type": "text/plain", "...": "...", "cut": []}
  ],
  "mime_tree_parts_left_out": 0
}
```

## Rules

1. One subprocess and one parse per request, as today. Do not run the CLI
   twice: it would double the CPU spent inside the 10-second timeout.
1. A response always has `mime_tree`. If the second document is missing
   or does not decode, the request fails with `422` like any other
   unparsable output; it is never answered with `message` alone.
1. Every value in the tree except the numbers, booleans and role names is
   text chosen by the sender. This service passes it on as JSON and does
   not interpret it. It never reaches a log line.
1. The tree grows with the number of MIME parts, which the sender
   chooses. The child's limits bound what it can print (see
   [Measurements](#measurements-2026-11-27)); the cut below bounds the
   response.
1. Errors are read from stderr. The detail of a `422` is the text after
   `An error occurred:` on stderr, `TOO_COMPLEX_ERROR` when that text is
   empty (a `MemoryError` has none), the generic error otherwise. stdout
   must start with `{`; anything else is unparsable output. stderr never
   reaches a log line.

## How a cut tree is reported

Decided with the owner on 2026-11-26, together with the same feature in
MailXRay (`docs/features/message-structure/spec.md` in mailxray-backend), so
that the live parser page and MailXRay read one shape:

- The response keeps the first 500 entries of the tree. Parents come before
  children, so what is kept is a valid tree.
- A new key beside `mime_tree`, `mime_tree_parts_left_out`, is the number of
  entries not kept, `0` when the tree is whole. It is always present.
- Every string value of an entry, the three values of `embedded_headers`
  included, is cut to 1024 characters. Every entry gains a key `cut`: the
  names of the keys that were cut (`embedded_headers.subject` for a nested
  one), an empty list otherwise.
- The kept entries hold at most 262,144 characters of text together: the
  characters of every string value, those of `embedded_headers` included,
  counted after the cut to 1024. Entries are kept in order while they fit;
  the first entry that would exceed the bound and every entry after it are
  left out and counted in `mime_tree_parts_left_out`. The kept entries are
  still a prefix, so the tree is still valid. Without this bound, 500
  entries of eleven values of 1024 characters hold 5.6 million characters,
  and a control character takes six bytes once escaped in JSON. MailXRay
  added the same bound after its security review of 2026-11-26 (rule 5 of
  "Bounds" in its spec); agreed for this service on 2026-11-27.

Decided on 2026-11-27: `message` is not cut. MailXRay also keeps only the
first 100 `received_header_defects`; this service does not, because
`message` stays what mail-parser prints.

MailXRay also refuses to build the tree of a message with more than 50,000
parts, by counting them first. This service cannot: the CLI builds the whole
tree in the child before anything is printed. The child's limits stay the
guard here, and such a message fails as too complex.

The service decodes the entries of the array one at a time and keeps only
those inside the bounds; the others are counted and dropped as soon as they
are decoded. Decoding the whole array first would hold up to 55 MiB of
objects per parse in uvicorn (PID 1), with two parses at once.

## Measurements (2026-11-27)

Docker on Apple silicon, `python:3.13-slim` (3.13.18, aarch64),
`mail-parser[outlook]==4.12.0`, a 512 MiB container, the child run as the
service runs it: `choom -n 1000 -- prlimit --as=201326592 --`,
`--json --mime-tree`, 10-second timeout.

| Email                                     | Result                                    |
| ----------------------------------------- | ----------------------------------------- |
| N empty parts (5 bytes each)              | passes up to 88,000; 91,000 and more fail |
| N tiny `text/plain` parts (32 bytes each) | passes up to 68,000; 70,000 and more fail |
| 5 MiB, one base64 attachment              | passes, 60.5 MiB child peak, as `--json`  |
| 5 MiB, twenty base64 attachments          | passes, 52.4 MiB child peak, as `--json`  |
| multipart nested N levels                 | passes up to 970; 980 and more fail       |

- Above the limit the child fails with `MemoryError` while printing the
  tree: exit code 1, the first document complete on stdout, nothing of the
  tree. That is unparsable output, a `422` with `TOO_COMPLEX_ERROR`. No run
  was killed and none came closer than 6.5 seconds to the timeout.
- Without `--mime-tree` the same cap passes about 250,000 empty parts: the
  tree lowers the limit to about 90,000.
- The largest tree that passes is 29 to 37 MB of JSON, about 420 bytes per
  entry. Holding and decoding it in the parent peaks at 125 MiB; two such
  parses at once peaked at 411 MiB in the container, without uvicorn.
- Nesting fails with `MailParserRecursionError` with or without
  `--mime-tree`; it is a limit of the parse, not of the tree.
- No lone surrogate reached stdout: the CLI writes UTF-8 with
  `ensure_ascii=False`, and undecodable bytes in tree values arrive as
  U+FFFD.

Decision (owner, 2026-11-27): failing above about 70,000 parts is
acceptable for the page; no count of our own before the parse.

## Acceptance

1. `POST /api/parse` with `mail_test_10` returns `200` with `message`
   equal to today's and a `mime_tree` of nine entries whose `attachment`
   values are 0 to 3.
1. A stub CLI that prints only the first document yields `422`.
1. A test covers an email with no MIME structure (one entry) and one
   nested several hundred levels deep.
1. A tree of 600 entries returns 500 and `mime_tree_parts_left_out == 100`;
   a file name of 5,000 characters returns 1024 of them and
   `cut == ["filename"]`; entries past 262,144 characters of text are left
   out and counted.
1. A failing CLI whose stderr has `An error occurred: <text>` yields `422`
   with `<text>`, and with `TOO_COMPLEX_ERROR` when the text is empty.
1. README endpoint contract updated with the new keys and the table above.
1. `make pre-commit` and `make test-cov` pass.
