# syntax=docker/dockerfile:1
# Explicit emulator fixture, using the production candidate's exact Wine source.
FROM docker.io/library/debian@sha256:a3bba7dc7dbcc1f37c2856c51fc9a7fac96608f50cb87b1b4e4d8b8c85ae988e AS base
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
COPY runtime/bridges/debian.sources /etc/apt/sources.list.d/debian.sources
COPY runtime/bridges/inrelease.SHA256SUMS runtime/wine-probe/sources.lock.json runtime/wine-probe/record_runtime.py runtime/wine-probe/capture_sources.py /opt/esteria-wine-probe/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    test "$(dpkg --print-architecture)" = amd64 \
    && echo '506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017  /usr/share/keyrings/debian-archive-keyring.gpg' | sha256sum --check \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /opt/esteria-wine-probe/inrelease.SHA256SUMS) \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca dist-upgrade -y --no-install-recommends

FROM base AS builder
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends \
      ca-certificates curl python3 build-essential gcc-mingw-w64-x86-64 \
      bison flex pkg-config libfreetype-dev libfontconfig-dev libx11-dev libxext-dev \
      libxrender-dev libxrandr-dev libxi-dev libxcursor-dev libxfixes-dev libxinerama-dev \
      libxxf86vm-dev libxcomposite-dev libxdamage-dev libvulkan-dev libgl-dev \
      libgnutls28-dev libasound2-dev libpulse-dev libdbus-1-dev libudev-dev libunwind-dev \
    && mkdir -p /sources /src /wine-build \
    && curl --fail --location --retry 3 --max-time 600 --cacert /run/secrets/build_ca \
      https://github.com/Russianranger/uo-android-launcher/releases/download/v0.2.0/wine-arm64ec-source.tar.gz \
      -o /sources/wine-arm64ec-source.tar.gz \
    && test "$(stat -c %s /sources/wine-arm64ec-source.tar.gz)" = 53416396 \
    && echo '93ffcd86d3f518934da5c93c768d43afe7e97d66f04f355d914f5cfb6731ac74  /sources/wine-arm64ec-source.tar.gz' | sha256sum --check \
    && tar --no-same-owner -xzf /sources/wine-arm64ec-source.tar.gz -C /src \
    && echo 'e237fa56668030e928551ddd60f05df5fe957f75eab874bbd017e085ed722e7c  /src/wine/COPYING.LIB' | sha256sum --check
RUN cd /wine-build \
    && /src/wine/configure --prefix=/opt/wine --enable-win64 --with-mingw=yes --disable-tests \
       --without-wayland --without-gstreamer --without-cups --without-sane --without-gphoto \
    && make -j2 && make install-strip DESTDIR=/out \
    && cp config.log /sources/wine-build-config.log \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n' > /sources/build-packages.tsv \
    && cp /src/wine/COPYING.LIB /sources/Wine-COPYING.LIB

FROM base AS runtime
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends \
      ca-certificates python3 libgl1-mesa-dri libglx-mesa0 libgl1 libvulkan1 mesa-vulkan-drivers \
      libx11-6 libxext6 libxrender1 libxrandr2 libxi6 libxfixes3 libxcursor1 libxinerama1 \
      libxxf86vm1 libxcomposite1 libxdamage1 libfontconfig1 libfreetype6 fonts-liberation \
      libasound2 libpulse0 libdbus-1-3 libudev1 libgnutls30 libunwind8 \
    && apt-get clean
COPY --from=builder /out/opt/wine /opt/wine
COPY --from=builder /sources/Wine-COPYING.LIB /usr/share/doc/esteria-wine-probe/COPYING.LIB
RUN python3 /opt/esteria-wine-probe/record_runtime.py \
      --lock /opt/esteria-wine-probe/sources.lock.json --output /etc/esteria-wine-probe.json \
    && rm -rf /var/lib/apt/lists/* /var/log/*
CMD ["/opt/wine/bin/wine", "--version"]

FROM builder AS corresponding-sources
COPY --from=runtime /etc/esteria-wine-probe.json /sources/runtime.json
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    python3 /opt/esteria-wine-probe/capture_sources.py --runtime /sources/runtime.json \
      --build-packages /sources/build-packages.tsv --lock /opt/esteria-wine-probe/sources.lock.json \
      --ca /run/secrets/build_ca --output /package-sources
FROM scratch AS source-export
COPY --from=corresponding-sources /sources/ /wine/
COPY --from=corresponding-sources /package-sources/ /debian/
