# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY src/ src/
COPY data/ data/
COPY opencode.json ./

# Expose and run
EXPOSE 8000
ENV DEUTSCH_HAUFIG_DATABASE_URL=sqlite:///data/app.db
CMD ["uv", "run", "web"]
