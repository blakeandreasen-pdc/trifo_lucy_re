# Unrooted Lucy local cloud: capture_server.py only (needs just PyYAML).
# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim
RUN pip install --no-cache-dir pyyaml==6.0.2 \
 && apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/* \
 && useradd -u 1000 -m lucy
WORKDIR /app
COPY server/ /app/
COPY docker/entrypoint.sh /entrypoint.sh
# runtime state lives in /data; the server writes next to its code, so link it there
RUN chmod 755 /entrypoint.sh \
 && for f in state.yaml schedule.json capture_log.txt mqtt_cert.pem mqtt_key.pem; do rm -f /app/$f; ln -s /data/$f /app/$f; done \
 && rm -f /app/config.yaml && ln -s /config/config.yaml /app/config.yaml \
 && mkdir /data && chown lucy:lucy /data
USER lucy
EXPOSE 443 7990 17766 8080
ENTRYPOINT ["/entrypoint.sh"]
