FROM python:3.12-alpine

ARG BUILD_VERSION=0.2.0
ARG BUILD_ARCH
ARG BUILD_REVISION=local

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/grayslawson/ha-switchboard" \
  org.opencontainers.image.revision="${BUILD_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY --chown=65532:65532 ha_switchboard /app/ha_switchboard
COPY --chown=65532:65532 run.sh /run.sh
COPY --chown=65532:65532 data/.keep /data/.keep

# Keep the entrypoint executable even when the build context is exported by a
# tool that does not preserve Git's executable-bit metadata. The application
# tree is immutable at runtime; only the Supervisor-mounted /data volume is
# handed to the guarded root-to-non-root transition in server.py.
RUN chmod 0555 /run.sh \
    && find /app -type d -exec chmod 0555 {} + \
    && find /app -type f -exec chmod 0444 {} + \
    && chmod 0700 /data

# Supervisor mounts /data as root-owned. Start briefly as root to make that
# directory writable, then drop to UID/GID 65532 before serving requests.
USER 0:0
EXPOSE 8099
ENTRYPOINT ["/run.sh"]
