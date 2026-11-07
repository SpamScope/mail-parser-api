FROM python:3.13-slim

RUN pip install --no-cache-dir uv

# Bytecode is compiled at build time because the container root filesystem is
# read-only at runtime.
ENV PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN uv sync --no-dev --frozen --no-install-project

COPY src/ src/

RUN uv sync --no-dev --frozen

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

USER app

EXPOSE 8000

# One worker keeps the in-memory rate limiter consistent; uvicorn's access log
# is replaced by the application's own, which omits client addresses. The
# concurrency limit is above the two parse slots so that health checks still
# get through while parses wait for a slot.
CMD ["uvicorn", "mail_parser_api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--limit-concurrency", "12", \
     "--no-access-log", "--no-server-header"]
