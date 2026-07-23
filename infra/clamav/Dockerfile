FROM python:3.11.13-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=60 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=60 install -y --no-install-recommends \
        clamav-daemon=1.4.3+dfsg-1~deb12u2 \
        clamav-freshclam=1.4.3+dfsg-1~deb12u2 \
    && chown -R clamav:clamav /var/lib/clamav

RUN rm -f /etc/clamav/clamd.conf /etc/clamav/freshclam.conf \
    && printf '%s\n' \
        'LogTime yes' \
        'Foreground yes' \
        'TCPSocket 3310' \
        'TCPAddr 0.0.0.0' \
        'User clamav' \
        'DatabaseDirectory /var/lib/clamav' \
        'TemporaryDirectory /tmp' \
        'MaxFileSize 25M' \
        'MaxScanSize 100M' \
        'StreamMaxLength 25M' \
        'ReadTimeout 120' \
        > /etc/clamav/clamd.conf \
    && printf '%s\n' \
        'DatabaseDirectory /var/lib/clamav' \
        'DatabaseMirror database.clamav.net' \
        'ReceiveTimeout 1800' \
        'UpdateLogFile /var/lib/clamav/freshclam.log' \
        'LogTime yes' \
        'Foreground yes' \
        > /etc/clamav/freshclam.conf

COPY infra/clamav/entrypoint.sh /usr/local/bin/rag-clamav-entrypoint
RUN chmod 0555 /usr/local/bin/rag-clamav-entrypoint

EXPOSE 3310
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=8 \
    CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 3310), 2); s.sendall(b'PING\\n'); assert s.recv(32).startswith(b'PONG')"

ENTRYPOINT ["/usr/local/bin/rag-clamav-entrypoint"]
