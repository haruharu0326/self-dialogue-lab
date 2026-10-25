# Build the React screen; only the static output is copied into the runtime image.
FROM node:24-slim AS screen
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SELF_DIALOGUE_DB=/app/data/demo.sqlite3 \
    SELF_DIALOGUE_PERSONAL_DB=/app/data/personal.sqlite3 \
    SELF_DIALOGUE_HOST=0.0.0.0 \
    SELF_DIALOGUE_PORT=8501

WORKDIR /app
ARG INSTALL_SENTIMENT=false

COPY pyproject.toml ./
COPY src ./src
COPY --from=screen /build/src/self_dialogue_lab/static ./src/self_dialogue_lab/static

RUN if [ "$INSTALL_SENTIMENT" = "true" ]; then \
      python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch>=2.4,<3' \
      && python -m pip install --no-cache-dir '.[sentiment]'; \
    else python -m pip install --no-cache-dir .; fi \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app/data /app/models \
    && chown app:app /app/data /app/models

ARG INSTALL_VOICE=false
RUN if [ "$INSTALL_VOICE" = "true" ]; then python -m pip install --no-cache-dir '.[voice]'; fi

USER app

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/api/health', timeout=3)" || exit 1

CMD ["python", "src/app.py"]
