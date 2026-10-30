# syntax=docker/dockerfile:1
# Native x86_64 build host only. The emitted guest is an opt-in debug fixture.
FROM docker.io/library/ubuntu@sha256:78d4744ead1f5b19b04d0df558ab182a5300903900755e515b2ca4d10eb2044d AS runtime
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
COPY runtime/server/ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources
COPY runtime/mysql-probe/sources.lock.json runtime/mysql-probe/mysql-binaries.SHA256SUMS runtime/mysql-probe/record_runtime.py runtime/server/inrelease.SHA256SUMS /opt/esteria-mysql-probe/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    test "$(dpkg --print-architecture)" = amd64 \
    && printf '%s\n' '#!/bin/sh' 'exit 101' > /usr/sbin/policy-rc.d \
    && chmod 755 /usr/sbin/policy-rc.d \
    && echo '80a36b0a6de2f69f49d2df75ef473ccde121e9e190b9ea01d20a4f63778d5c31  /usr/share/keyrings/ubuntu-archive-keyring.gpg' | sha256sum --check \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /opt/esteria-mysql-probe/inrelease.SHA256SUMS) \
    && mkdir /tmp/esteria-mysql-pins \
    && (cd /tmp/esteria-mysql-pins \
        && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca download \
           mysql-server-core-8.0=8.0.46-0ubuntu0.24.04.4 mysql-client-core-8.0=8.0.46-0ubuntu0.24.04.4 \
           libmysqlclient21=8.0.46-0ubuntu0.24.04.4 \
        && sha256sum --check /opt/esteria-mysql-probe/mysql-binaries.SHA256SUMS) \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca dist-upgrade -y --no-install-recommends \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends \
       ca-certificates python3 mysql-server-core-8.0=8.0.46-0ubuntu0.24.04.4 \
       mysql-client-core-8.0=8.0.46-0ubuntu0.24.04.4 libmysqlclient21=8.0.46-0ubuntu0.24.04.4 \
    && python3 /opt/esteria-mysql-probe/record_runtime.py \
       --lock /opt/esteria-mysql-probe/sources.lock.json --output /etc/esteria-mysql-probe.json \
    && apt-get clean && rm -rf /tmp/esteria-mysql-pins /var/lib/apt/lists/* \
    && test ! -e /var/lib/mysql/auto.cnf
CMD ["/usr/bin/python3", "--version"]

FROM runtime AS corresponding-sources
# This existing source collector is architecture-neutral and retains each exact installed source version.
COPY runtime/server/capture_sources.py /opt/esteria-mysql-probe/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /opt/esteria-mysql-probe/inrelease.SHA256SUMS) \
    && python3 /opt/esteria-mysql-probe/capture_sources.py \
       --runtime /etc/esteria-mysql-probe.json --lock /opt/esteria-mysql-probe/sources.lock.json \
       --ca /run/secrets/build_ca --output /source-archives
FROM scratch AS source-export
COPY --from=corresponding-sources /source-archives/ /
