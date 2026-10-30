# syntax=docker/dockerfile:1
# Build on a native ARM64 host. This is a build tool, never an Android dependency.
FROM docker.io/library/ubuntu@sha256:19cad59657037cffa0ac9a48107019b768900ff1071140965827513ac866bd5e AS runtime
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
COPY ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources
COPY sources.lock.json inrelease.SHA256SUMS mysql-binaries.SHA256SUMS record_runtime.py /opt/esteria-runtime/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    test "$(dpkg --print-architecture)" = arm64 \
    && printf '%s\n' '#!/bin/sh' 'exit 101' > /usr/sbin/policy-rc.d \
    && chmod 755 /usr/sbin/policy-rc.d \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /opt/esteria-runtime/inrelease.SHA256SUMS) \
    && mkdir /tmp/esteria-mysql-pins \
    && (cd /tmp/esteria-mysql-pins \
        && apt-get -o Acquire::Retries=3 -o Acquire::https::CaInfo=/run/secrets/build_ca download \
           mysql-server-core-8.0=8.0.46-0ubuntu0.24.04.4 \
           mysql-client-core-8.0=8.0.46-0ubuntu0.24.04.4 \
           libmysqlclient21=8.0.46-0ubuntu0.24.04.4 \
        && sha256sum --check /opt/esteria-runtime/mysql-binaries.SHA256SUMS) \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::CaInfo=/run/secrets/build_ca dist-upgrade -y --no-install-recommends \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends \
       ca-certificates python3 \
       mysql-server-core-8.0=8.0.46-0ubuntu0.24.04.4 \
       mysql-client-core-8.0=8.0.46-0ubuntu0.24.04.4 \
       libmysqlclient21=8.0.46-0ubuntu0.24.04.4 \
       libboost-filesystem1.83.0 libboost-program-options1.83.0 libboost-iostreams1.83.0 \
       libboost-regex1.83.0 libboost-thread1.83.0 libreadline8t64 libbz2-1.0 zlib1g libssl3t64 \
    && python3 /opt/esteria-runtime/record_runtime.py \
       --lock /opt/esteria-runtime/sources.lock.json --output /etc/esteria-server-runtime.json \
    && apt-get clean \
    && rm -rf /tmp/esteria-mysql-pins \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /esteria-state /esteria-content /esteria-server \
    && test ! -e /var/lib/mysql/auto.cnf
CMD ["/usr/bin/python3", "--version"]

# This target retains exact corresponding sources for every installed package.
# It intentionally downloads substantial source archives (MySQL alone ~493 MB).
FROM runtime AS corresponding-sources
COPY capture_sources.py /opt/esteria-runtime/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::Retries=3 -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /opt/esteria-runtime/inrelease.SHA256SUMS) \
    && python3 /opt/esteria-runtime/capture_sources.py \
       --runtime /etc/esteria-server-runtime.json --lock /opt/esteria-runtime/sources.lock.json \
       --ca /run/secrets/build_ca --output /source-archives

FROM scratch AS source-export
COPY --from=corresponding-sources /source-archives/ /
