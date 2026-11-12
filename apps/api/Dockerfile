FROM python:3.12.16-slim-trixie@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54

# Freeze the Debian package universe used by this image. Bump this timestamp
# deliberately when refreshing OS packages and reviewing the resulting SBOM.
# Upgrade inherited packages from the same snapshot so security fixes are not
# left behind in the pinned Python base image.
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
    apt-get install -y --no-install-recommends ffmpeg=7:7.1.5-0+deb13u1; \
    test "$(dpkg-query -W -f='${Version}' ffmpeg)" = "7:7.1.5-0+deb13u1"; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
