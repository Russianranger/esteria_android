# syntax=docker/dockerfile:1
FROM docker.io/library/debian@sha256:7ccb8b5b60c7654f5b795d94ee7d751cd0811500803f0b09cefcd555e755a55a AS build
ENV DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
COPY debian.sources /etc/apt/sources.list.d/debian.sources
COPY sources.lock.json packages.txt inrelease.SHA256SUMS record_build.py capture_sources.py /inputs/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    test "$(dpkg --print-architecture)" = arm64 \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /inputs/inrelease.SHA256SUMS) \
    && mkdir /package-pins \
    && (cd /package-pins && xargs -a /inputs/packages.txt apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca download) \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends python3 /package-pins/*.deb \
    && python3 /inputs/record_build.py --verify-inputs
COPY --from=bridge-src /guest-bridges/ /src/guest-bridges/
COPY --from=bridge-src /presentation/frame_protocol.h /presentation/frame_transport.h /src/presentation/
ARG INTEGRATION_REVISION
RUN make -C /src/guest-bridges OUT=/out/bin \
    && mkdir -p /out/notices /out/corresponding-source \
    && cp /usr/share/doc/libxtst-dev/copyright /out/notices/libxtst-copyright \
    && cp /src/guest-bridges/AUDIO-LICENSE /out/notices/AUDIO-LICENSE \
    && cp -r /src/guest-bridges /src/presentation /out/corresponding-source/ \
    && python3 /inputs/record_build.py --revision "$INTEGRATION_REVISION"
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    python3 /inputs/capture_sources.py --ca /run/secrets/build_ca
FROM scratch AS guest-export
COPY --from=build /out/ /
COPY sources.lock.json packages.txt debian.sources inrelease.SHA256SUMS Dockerfile record_build.py capture_sources.py /corresponding-source/build-recipe/

# An observer is a test fixture, never a fourth production bridge binary.
# Its source is deliberately outside /src and the production receipt inventory.
FROM build AS x11-fixture-build
COPY --from=bridge-src /guest-tests/x11_input_observer.c /fixture-src/x11_input_observer.c
COPY record_x11_fixture.py /inputs/
RUN mkdir -p /out/x11-test \
    && gcc -std=c11 -O2 -Wall -Wextra -Werror /fixture-src/x11_input_observer.c -lX11 -o /out/x11-test/esteria-x11-input-observer \
    && cp /fixture-src/x11_input_observer.c /out/x11-test/ \
    && python3 /inputs/record_x11_fixture.py
FROM scratch AS x11-test-export
COPY --from=x11-fixture-build /out/ /
COPY sources.lock.json packages.txt debian.sources inrelease.SHA256SUMS Dockerfile record_build.py record_x11_fixture.py capture_sources.py /corresponding-source/build-recipe/
