# mail-parser-api

Stateless HTTP API that parses raw emails with
[mail-parser](https://github.com/SpamScope/mail-parser) and returns the parsed
message as JSON. It powers the live parser on [spamscope.ai](https://spamscope.ai).

Nothing is stored: each email is parsed in memory, in a short-lived subprocess,
and only the JSON goes back to the caller.

## Endpoint contract

### `POST /api/parse`

Send the raw email as the request body with `Content-Type: message/rfc822`.

```bash
curl -s -H 'Content-Type: message/rfc822' --data-binary @email.eml \
  http://localhost:8000/api/parse
```

Response `200`:

```json
{
  "mail_parser_version": "4.12.0",
  "message": {"subject": "...", "attachments": [{"filename": "...", "binary": true}]},
  "mime_tree": [
    {"index": 0, "parent": null, "depth": 0, "content_type": "multipart/mixed", "...": "...", "cut": []},
    {"index": 1, "parent": 0, "depth": 1, "content_type": "text/plain", "...": "...", "cut": []}
  ],
  "mime_tree_parts_left_out": 0
}
```

`message` is the full `mail_json` of mail-parser. Every entry of `attachments`
keeps its metadata and loses the `payload` key.

`mime_tree` is the MIME tree of the email, as mail-parser's `--mime-tree`
prints it: a flat list in which entry `i` is MIME part `i` (the `part N` of
defect messages) and names its enclosing part in `parent`. Every entry has
these keys:

| Key                         | Type          | Meaning                                                                        |
| --------------------------- | ------------- | ------------------------------------------------------------------------------ |
| `index`                     | int           | Position in the list.                                                          |
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
| `roles`                     | list          | Any of `container`, `body`, `attachment`.                                      |
| `attachment`                | int / null    | Position of the matching entry in `message.attachments`.                       |
| `defects`                   | list          | Names of the defect categories recorded against the part.                      |
| `recovered`                 | bool          | True for a part recovered from an epilogue.                                    |
| `embedded_headers`          | object / null | Literal `from`, `subject`, `date` of a message enclosed in a `message/*` part. |
| `cut`                       | list          | Keys whose value was cut to 1024 characters (`embedded_headers.subject`).      |

Every string in the tree, except the role and defect names, is text chosen
by the sender, passed on as declared: control characters and bidirectional
overrides included. A client must escape it before showing it.

The tree is bounded, and nothing is dropped silently:

- at most the first 500 entries are kept; parents come before children, so
  what is kept is still a tree;
- every string value, those of `embedded_headers` included, is cut to 1024
  characters, and its key is named in `cut`;
- the kept entries hold at most 262,144 characters of text together; the
  first entry that would exceed it and every entry after it are left out.

`mime_tree_parts_left_out` is the number of entries left out, `0` when the
tree is whole. `message` is never cut: it is whole or the request fails
(see the output cap below).

| Status | When                                                         | Body                                                |
| ------ | ------------------------------------------------------------ | --------------------------------------------------- |
| `413`  | Body larger than 5 MB                                        | `{"detail": "Body exceeds 5 MB"}`                   |
| `415`  | `Content-Type` is not `message/rfc822`                       | `{"detail": "Content-Type must be message/rfc822"}` |
| `415`  | `Content-Type` is `application/vnd.ms-outlook`               | `{"detail": "Outlook .msg not supported yet"}`      |
| `422`  | mail-parser fails on the email                               | `{"detail": "<mail-parser error message>"}`         |
| `429`  | More than 10 requests in 60 seconds from the same client key | `{"detail": "Too many requests"}`                   |
| `504`  | Parsing takes longer than 10 seconds                         | `{"detail": "Parsing timed out"}`                   |

mail-parser is tolerant: most malformed emails still return `200`, with
`has_defects` and `defects_categories` describing the problems.

### `GET /healthz`

Returns `200` with `{"status": "ok"}`. It is meant for container health checks;
the reverse proxy does not expose it.

## Limits and isolation

- Each request runs the installed mail-parser CLI
  (`mail-parser --stdin --json --mime-tree`) in a subprocess, once. The email goes to its stdin, never through a shell; the
  subprocess is killed after 10 seconds.
- The request body is limited to 5 MB.
- At most 2 emails are parsed at once; further requests wait for a free slot.
- In the container each parse is limited to 192 MiB of address space
  (`prlimit`) and is the first process the kernel kills when memory runs out
  (`choom`), so the server survives. Such an email gets `422` with
  `email too complex to parse within the service limits`. Measured with
  mail-parser 4.12.0, the limit falls past 970 levels of nesting; a 5 MB
  email of base64 attachments passes.
- The CLI may print at most 16 MiB, the mail and the MIME tree together:
  its stdout goes to a temporary file in `/tmp`, which `prlimit --fsize`
  caps in the container. An email that reaches it gets the same `422`. A
  real 5 MB email prints 5 to 7 MB; the cap is reached by emails full of
  control characters, which JSON prints as six bytes each, or with more than
  about 35,000 MIME parts.
- Rate limit: 10 requests per 60-second sliding window per client key, in
  memory, for at most 10 000 keys (least recently used evicted first). The
  client key is the first `X-Forwarded-For` value, or the peer address without
  it: an IPv4 address whole, an IPv6 address collapsed to its `/64`. The header
  is trusted because the service runs only behind a reverse proxy that sets it.
- uvicorn runs one worker with `--limit-concurrency 12`, above the parse
  slots so that health checks still get through.
- The access log has only method, path, status and response size. Request
  bodies and email headers are never logged.
- The container image runs as a non-root user and works with a read-only root
  filesystem, all capabilities dropped and a `tmpfs` on `/tmp`.

## Run locally

Requirements: [uv](https://docs.astral.sh/uv/) and, for the container, Docker.

```bash
make install
uv run uvicorn mail_parser_api.app:create_app --factory --port 8000
```

With Docker Compose, using the same hardening as production:

```bash
make up     # build and start on http://localhost:8000
make down
```

## Development

```bash
make pre-commit   # ruff, ruff-format, pyright, mdformat, markdownlint, ...
make test-cov     # tests with coverage
```

See [CLAUDE.md](CLAUDE.md) for the coding rules.

## Release process

Every pull request to `main` needs exactly one release label: `major_release`,
`minor_release` or `patch_release`. CI checks the label, then runs lint, tests
and a `linux/amd64` image build without pushing (`lint-test-build`, required
before merge), so a broken lockfile or Dockerfile fails before a tag exists.

When the pull request is squash-merged, the release workflow
(`pull_request_target`, so merged fork pull requests release too; it never
checks out pull request code) runs one release at a time and:

1. bumps `__version__` in `src/mail_parser_api/__init__.py` according to the
   label and tags `vX.Y.Z`, pushed with the `RELEASE_DEPLOY_KEY` deploy key,
   a secret of the `release` environment that only `main` can use;
1. publishes `ghcr.io/spamscope/mail-parser-api:X.Y.Z` and `:latest` for
   `linux/amd64` and `linux/arm64`;
1. creates the GitHub release with generated notes.

Two rulesets protect `main`. `main` requires a pull request and the
`lint-test-build` check; the deploy key is its only bypass actor, so the bump
commit can land without a pull request. `main-protect` blocks deletion and
force pushes with no bypass, not even for the deploy key.

Dependabot opens weekly pull requests, labelled `patch_release`, for production
dependencies and GitHub Actions, so a new mail-parser on PyPI becomes a new
release and a new image.

## License

[Apache-2.0](LICENSE)
