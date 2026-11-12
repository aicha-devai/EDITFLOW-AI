FROM python:3.12.16-slim-trixie@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS runtime-base

# Pin the Debian package universe. Refresh this timestamp only with a reviewed
# SBOM and security scan; both runtime targets inherit this patched base.
ARG DEBIAN_SNAPSHOT=20261112T000000Z
RUN set -eux; \
    rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*; \
    printf '%s\n' \
      "Types: deb" \
      "URIs: https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" \
      "Suites: trixie trixie-updates" \
      "Components: main" \
      "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" \
      "Check-Valid-Until: no" \
      "" \
      "Types: deb" \
      "URIs: https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}" \
      "Suites: trixie-security" \
      "Components: main" \
      "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" \
      "Check-Valid-Until: no" \
      > /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get upgrade -y --no-install-recommends; \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 alembic.ini ./alembic.ini
RUN groupadd --gid 10001 editflow && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin editflow

# Only the isolated render worker receives FFmpeg/FFprobe. It runs as the same
# unprivileged UID and is additionally sandboxed by the production Compose file.
FROM runtime-base AS worker
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg=7:7.1.5-0+deb13u1; \
    test "$(dpkg-query -W -f='${Version}' ffmpeg)" = "7:7.1.5-0+deb13u1"; \
    rm -rf /var/lib/apt/lists/*
USER 10001:10001
CMD ["python", "-m", "app.worker_main"]

# The public API does not need the FFmpeg command-line tools. Keep the media
# parser/encoder toolchain out of this internet-facing runtime image.
FROM runtime-base AS api
USER 10001:10001
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

