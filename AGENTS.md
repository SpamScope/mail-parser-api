# AGENTS.md

Shared instructions for coding agents. `CLAUDE.md` imports this file, so Claude
and Codex follow the same rules.

## Language

- Write all code, comments, docstrings, commit messages, and documentation in English.
- Everything under `docs/` (specs, issues, ADRs, agent docs) must be in English.
- This applies even when the conversation with the user is in another language
  (e.g. Italian): chat language never changes the language of repository content.

## Security

- The service handles untrusted emails: never log request bodies, email
  headers, or any email content, and keep email content out of exception
  messages.
- Parse emails only in the mail-parser subprocess: fixed argument list, email on
  stdin, timeout. Never use `shell=True` or pass input as arguments.
- Validate and reject input at the HTTP boundary (content type, size, rate limit)
  before parsing.
- Never hardcode secrets, tokens, or credentials. The only secret is the
  `RELEASE_DEPLOY_KEY` GitHub secret used by the release workflow.
- Pin dependency versions in `uv.lock`.

## Engineering Principles

- **DRY** — extract repeated logic; no copy-paste code.
- **KISS** — simplest solution that works; no clever tricks.
- **YAGNI** — no code for hypothetical future needs.
- **SRP** — one function/class, one responsibility.
- **Fail fast** — validate at boundaries; trust internal code.
- No dead code, commented-out blocks, or unused imports.
- Every third-party import must have an explicit entry in `pyproject.toml`. Use extras when the runtime feature requires them (e.g. `mail-parser[outlook]`).

## Python Style

- Follow PEP 8. Use 4 spaces, never tabs.
- Lines: 88 chars max (enforced by ruff `line-length`).
- `snake_case` for functions/variables, `CapWords` for classes, `UPPER_CASE` for constants.
- Imports order: stdlib → third-party → local.
- Add docstrings to all public functions, methods, classes, and modules (params, return values, exceptions).

## Stack

- Python 3.13+, package manager: **uv**, build backend: **hatchling**
- Web framework: **FastAPI** served by **uvicorn**
- Parser: **mail-parser** CLI, run in a subprocess
- Linter/formatter: **ruff** (line-length 88, aggressive rule set — see `pyproject.toml`)
- Type checker: **pyright** (runs as pre-commit hook on `src/` and `tests/`)
- Tests: **pytest** with `tests/unittests/` layout and FastAPI `TestClient`

## Project Layout

```text
src/mail_parser_api/
  app.py         # FastAPI app: routes, request checks, access log
  parser.py      # mail-parser subprocess and JSON shaping
  rate_limit.py  # in-memory per-client rate limiter
tests/unittests/ # mirrors src layout; sample emails in files/
```

## Workflow

After every change:

1. Add/update unittests to cover the change.
1. Update README.md if the change affects usage, API, limits, or setup.
1. Stage changes and run pre-commit; fix all reported issues before proceeding.
1. Run full test suite; fix all failures before reporting done.

```bash
git add <changed files>
make pre-commit
make test
```

Every pull request needs exactly one release label (`major_release`,
`minor_release`, `patch_release`); see the release process in `README.md`.

## Commands

```bash
make install      # install dependencies via uv
make test         # run tests
make test-cov     # run tests with coverage (HTML report in htmlcov/)
make lint         # ruff check
make lint-fix     # ruff check --fix
make format       # ruff format
make pre-commit   # run all pre-commit hooks
make clean        # remove build artifacts and caches
make up           # build and start the container on port 8000
make down         # stop the container
```

Run single test: `uv run pytest tests/unittests/path/to/test_file.py::test_name`
Type check: `uv run pyright src/ tests/`

## Ruff Rules

Strict config — many rule families enabled. Key ignores:

- `D100`, `D104`: no module/package docstrings required
- `D203`/`D213` disabled (use `D211`/`D212`)
- `tests/**`: `S101` (assert), `ANN`, `D` all ignored

## Agent skills

### Issue tracker

Issues and specs live as markdown files under `docs/features/<feature-slug>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, used verbatim (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root, both created lazily. See `docs/agents/domain.md`.
