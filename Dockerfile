FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SELF_DIALOGUE_DB=/app/data/demo.sqlite3 \
    SELF_DIALOGUE_PERSONAL_DB=/app/data/personal.sqlite3

WORKDIR /app
ARG INSTALL_SENTIMENT=false

COPY pyproject.toml ./
COPY src ./src
COPY .streamlit/config.toml ./.streamlit/config.toml

RUN if [ "$INSTALL_SENTIMENT" = "true" ]; then \
      python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch>=2.4,<3' \
      && python -m pip install --no-cache-dir '.[sentiment]'; \
    else python -m pip install --no-cache-dir .; fi \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app/data /app/models \
    && chown app:app /app/data /app/models

USER app

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1

CMD ["python", "-m", "streamlit", "run", "src/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
