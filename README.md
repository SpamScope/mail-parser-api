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
  "mail_parser_version": "4.10.0",
  "message": {"subject": "...", "attachments": [{"filename": "...", "binary": true}]}
}
```

`message` is the full `mail_json` of mail-parser. Every entry of `attachments`
keeps its metadata and loses the `payload` key.

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

- Each request runs the installed mail-parser CLI (`mail-parser --stdin --json`)
  in a subprocess. The email goes to its stdin, never through a shell; the
  subprocess is killed after 10 seconds.
- The request body is limited to 5 MB.
- At most 2 emails are parsed at once; further requests wait for a free slot.
- In the container each parse is limited to 192 MiB of address space
  (`prlimit`) and is the first process the kernel kills when memory runs out
  (`choom`), so the server survives. Such an email gets `422` with
  `email too complex to parse within the service limits`.
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
and the package build (`lint-test-build`, required by the `main` ruleset).

When the pull request is squash-merged, the release workflow:

1. bumps `__version__` in `src/mail_parser_api/__init__.py` according to the
   label and tags `vX.Y.Z` (pushed with the `RELEASE_DEPLOY_KEY` deploy key,
   the only bypass actor of the ruleset);
1. publishes `ghcr.io/spamscope/mail-parser-api:X.Y.Z` and `:latest` for
   `linux/amd64` and `linux/arm64`;
1. creates the GitHub release with generated notes.

Dependabot opens weekly pull requests, labelled `patch_release`, for production
dependencies and GitHub Actions, so a new mail-parser on PyPI becomes a new
release and a new image.

## License

[Apache-2.0](LICENSE)
