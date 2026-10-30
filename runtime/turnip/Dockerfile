# syntax=docker/dockerfile:1
FROM docker.io/library/debian@sha256:7ccb8b5b60c7654f5b795d94ee7d751cd0811500803f0b09cefcd555e755a55a AS build
ENV DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
COPY debian.sources /etc/apt/sources.list.d/debian.sources
COPY . /inputs/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    test "$(dpkg --print-architecture)" = arm64 \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /inputs/inrelease.SHA256SUMS) \
    && mkdir /package-pins /src \
    && (cd /package-pins && xargs -a /inputs/packages.txt apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca download) \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends /package-pins/*.deb \
    && python3 /inputs/record_build.py --verify-inputs \
    && python3 /inputs/fetch_sources.py --ca /run/secrets/build_ca
ARG INTEGRATION_REVISION
RUN INTEGRATION_REVISION="$INTEGRATION_REVISION" sh /inputs/build.sh
FROM scratch AS turnip-export
COPY --from=build /out/ /
