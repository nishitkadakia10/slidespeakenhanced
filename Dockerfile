FROM python:3.12.9-slim

COPY --from=ghcr.io/astral-sh/uv:0.6.10 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml pyproject.toml

COPY uv.lock uv.lock

RUN uv sync --frozen

COPY slidespeak.py slidespeak.py

CMD ["uv", "run", "slidespeak.py"]