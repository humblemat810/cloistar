# Build context must be the repo root:
#   docker build -t kogwistar-bridge:local -f bridge/Dockerfile .
#
# The multi-stage build keeps the final image slim while bundling the
# kogwistar library and pydantic_extension from the local source tree.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# ── runtime dependencies ─────────────────────────────────────────────────────
COPY bridge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── local library: pydantic_extension ────────────────────────────────────────
COPY pydantic_extension ./pydantic_extension

# ── local library: kogwistar (the Python library sub-tree) ───────────────────
# We install it as an editable-equivalent by first copying and then doing a
# lightweight local install (no build isolation needed for pure-Python code).
COPY kogwistar ./kogwistar
RUN pip install --no-cache-dir \
        --no-build-isolation \
        --find-links /app \
        "./kogwistar[server]"

# ── bridge application ───────────────────────────────────────────────────────
COPY bridge/app ./app

# Optional: scripts used by the approval-listener feature
COPY scripts ./scripts

EXPOSE 8799

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8799"]
