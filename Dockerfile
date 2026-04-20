# Knowledge-Assist Answer Generation — Cloud Run
# Optimized for layer caching and smaller image

FROM python:3.13-slim

WORKDIR /app

# Install uv (faster than pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency manifests first (best layer caching)
COPY pyproject.toml ./

# Install dependencies (no dev); project installed in next step
RUN uv sync --no-dev --no-install-project

# Copy only runtime-necessary files (no secrets/.env in image)
COPY main.py ./
COPY src/ ./src/
#COPY configs/__init__.py configs/settings.py configs/bootstrap_secrets.py ./configs/
COPY configs/ ./configs/

# Install project into existing venv
RUN uv sync --no-dev

# Cloud Run sets PORT (default 8000)
ENV PORT=8000
EXPOSE 8000

# Use venv's uvicorn directly for faster startup (no uv run overhead)
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

