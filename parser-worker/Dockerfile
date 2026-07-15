FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PARSER_JOB_DIR=/tmp/parser-jobs

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=60 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=60 install -y --no-install-recommends \
        git libreoffice-writer libreoffice-calc libreoffice-impress \
    && useradd --create-home --uid 10001 parser

WORKDIR /worker
COPY parser-worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY parser-worker/parser_worker ./parser_worker
RUN mkdir -p /tmp/parser-jobs && chown -R parser:parser /tmp/parser-jobs /worker

USER parser
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"
CMD ["uvicorn", "parser_worker.app:app", "--host", "0.0.0.0", "--port", "8090"]
