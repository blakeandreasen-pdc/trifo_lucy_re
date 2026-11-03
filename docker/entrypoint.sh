#!/bin/sh
set -e
# Lucy doesn't verify the cert; self-signed is what upstream uses
if [ ! -f /data/mqtt_cert.pem ]; then
  openssl req -x509 -newkey rsa:2048 -keyout /data/mqtt_key.pem -out /data/mqtt_cert.pem \
    -days 3650 -nodes -subj "/CN=euiot.trifo.com" 2>/dev/null
  chmod 600 /data/mqtt_key.pem
fi
exec python -u /app/capture_server.py
