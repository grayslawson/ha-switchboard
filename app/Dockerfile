FROM python:3.12-alpine

ARG BUILD_VERSION=0.1.2
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/grayslawson/ha-switchboard"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY --chown=65532:65532 ha_switchboard /app/ha_switchboard
COPY --chown=65532:65532 run.sh /run.sh
COPY --chown=65532:65532 data/.keep /data/.keep

# Keep the entrypoint executable even when the build context is exported by a
# tool that does not preserve Git's executable-bit metadata.
RUN chmod 0555 /run.sh

# Use a numeric unprivileged identity so the same Dockerfile can be assembled
# for amd64 and arm64 without executing target-architecture binaries during
# the multi-architecture CI build. The base image's /bin/sh runs natively at
# App startup on the user's Home Assistant host.
USER 65532:65532
EXPOSE 8099
ENTRYPOINT ["/run.sh"]
