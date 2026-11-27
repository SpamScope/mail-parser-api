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
   document ends. An empty tree is `[]`.

Log lines can still precede the first document, as today.

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
   chooses, and so does the response. Measure the response and the
   child's memory for a 5 MB email made of as many tiny parts as fit, and
   for one nested several hundred levels deep, before deciding whether the
   existing limits are enough or the tree needs its own.
   Measured in mail-parser (Python 3.13, macOS) on a 2.7 MiB message of
   400,000 empty parts: the tree is 159 MiB of JSON, about 400 bytes per
   entry, and producing it peaks at 626 MiB, against 281 MiB for parsing
   alone. Under the 192 MiB cap such a message fails as too complex; the
   open point is the largest tree that still passes.

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

MailXRay also refuses to build the tree of a message with more than 50,000
parts, by counting them first. This service cannot: the CLI builds the whole
tree in the child before anything is printed. The child's limits stay the
guard here, and such a message fails as too complex.

## Open questions for the implementation

- The cut above bounds the response, not the child. What is the largest tree
  the child still produces under the 192 MiB cap, and is failing above it
  acceptable for the page?
- Reading the tree makes mail-parser decode each base64 attachment once to
  measure it. Does a 5 MB email stay inside the 192 MiB address-space cap?

## Acceptance

1. `POST /api/parse` with `mail_test_10` returns `200` with `message`
   equal to today's and a `mime_tree` of nine entries whose `attachment`
   values are 0 to 3.
1. A stub CLI that prints only the first document yields `422`.
1. A test covers an email with no MIME structure (one entry) and one
   nested several hundred levels deep.
1. README endpoint contract updated with the new key and the table above.
1. `make pre-commit` and `make test-cov` pass.
