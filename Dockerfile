FROM python:3.11-slim AS base

WORKDIR /app

COPY pyproject.toml README.md ./
RUN mkdir -p agents shared tools knowledge evaluator demo scripts && \
    touch agents/__init__.py shared/__init__.py tools/__init__.py \
          knowledge/__init__.py evaluator/__init__.py demo/__init__.py && \
    pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir -e ".[dev]"

COPY agents/ agents/
COPY shared/ shared/
COPY tools/ tools/
COPY knowledge/ knowledge/
COPY evaluator/ evaluator/
COPY demo/ demo/
COPY scripts/ scripts/

RUN mkdir -p audit chroma_db

ENV PYTHONUNBUFFERED=1

FROM base AS test
COPY tests/ tests/
CMD ["pytest", "--tb=short", "-q"]

FROM base AS app
ENV DEMO_MODE=true
EXPOSE 8000
CMD ["uvicorn", "demo.app:app", "--host", "0.0.0.0", "--port", "8000"]
