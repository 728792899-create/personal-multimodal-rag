#!/bin/sh
set -eu

if [ ! -s /var/lib/clamav/main.cvd ] && [ ! -s /var/lib/clamav/main.cld ]; then
  freshclam --config-file=/etc/clamav/freshclam.conf
else
  freshclam --config-file=/etc/clamav/freshclam.conf || true
fi

exec clamd --config-file=/etc/clamav/clamd.conf
