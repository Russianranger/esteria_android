# syntax=docker/dockerfile:1
# Separate native ARM64 candidate. The existing f036 provider is never modified.
FROM docker.io/library/debian@sha256:7ccb8b5b60c7654f5b795d94ee7d751cd0811500803f0b09cefcd555e755a55a AS base
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
COPY runtime/bridges/debian.sources /etc/apt/sources.list.d/debian.sources
COPY runtime/bridges/inrelease.SHA256SUMS /inputs/inrelease.SHA256SUMS
COPY runtime/wine-arm64/sources.lock.json runtime/wine-arm64/record_runtime.py /inputs/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    test "$(dpkg --print-architecture)" = arm64 \
    && echo '506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017  /usr/share/keyrings/debian-archive-keyring.gpg' | sha256sum --check \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /inputs/inrelease.SHA256SUMS) \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca dist-upgrade -y --no-install-recommends

FROM base AS builder
COPY runtime/wine-arm64/ /inputs/
COPY runtime/wine-probe/apply_adaptations.py runtime/wine-probe/android-private-pe-copy.patch \
     runtime/wine-probe/capture_sources.py /inputs/
COPY tools/prepare_runtime.py tools/owned_process_group.py /inputs/
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends \
      ca-certificates curl git xz-utils cmake ninja-build python3 build-essential patch bison flex pkg-config \
      libfreetype-dev libfontconfig-dev libx11-dev libxext-dev libxrender-dev libxrandr-dev libxi-dev \
      libxcursor-dev libxfixes-dev libxinerama-dev libxxf86vm-dev libxcomposite-dev libxdamage-dev \
      libvulkan-dev libgl-dev libgnutls28-dev libasound2-dev libpulse-dev libdbus-1-dev libudev-dev libunwind-dev \
    && SSL_CERT_FILE=/run/secrets/build_ca python3 /inputs/fetch_inputs.py --lock /inputs/sources.lock.json --download /sources
# Unpacked compilers/source/build objects live in this layer only, keeping disk bounded.
RUN mkdir -p /toolchain /src /wine-build /private-pe-fixtures \
    && tar --no-same-owner -xJf /sources/llvm-mingw-20250920-ucrt-ubuntu-22.04-aarch64.tar.xz --strip-components=1 -C /toolchain \
    && python3 /inputs/fetch_inputs.py --lock /inputs/sources.lock.json --toolchain /toolchain --output /sources/toolchain-metadata.json \
    && tar --no-same-owner -xzf /sources/wine-arm64ec-source.tar.gz -C /src \
    && echo 'e237fa56668030e928551ddd60f05df5fe957f75eab874bbd017e085ed722e7c  /src/wine/COPYING.LIB' | sha256sum --check \
    && python3 /inputs/apply_adaptations.py --lock /inputs/sources.lock.json --inputs /inputs \
         --source /src/wine --output /sources/android-private-pe-copy \
    && PATH=/toolchain/bin:$PATH /toolchain/bin/aarch64-w64-mingw32-clang -O2 -Wall -Wextra -Werror -shared \
         /inputs/private_pe_fixture.c -o /private-pe-fixtures/private-pe-fixture.dll -Wl,--image-base,0x180000000 \
    && /toolchain/bin/llvm-objcopy --set-section-flags .shared=alloc,load,data,contents,share /private-pe-fixtures/private-pe-fixture.dll \
    && PATH=/toolchain/bin:$PATH /toolchain/bin/aarch64-w64-mingw32-clang -O2 -Wall -Wextra -Werror \
         /inputs/private_pe_check.c -o /private-pe-fixtures/private-pe-check.exe \
    && cp /inputs/private_pe_check.py /inputs/owned_process_group.py /private-pe-fixtures/ \
    && cd /wine-build \
    && PATH=/toolchain/bin:$PATH /src/wine/configure --prefix=/opt/wine \
         --enable-archs=arm64ec,aarch64,i386 --with-mingw=clang --disable-tests \
         --without-wayland --without-gstreamer --without-cups --without-sane --without-gphoto \
    && PATH=/toolchain/bin:$PATH make -s -j2 \
    && PATH=/toolchain/bin:$PATH make -s install INSTALL_PROGRAM_FLAGS=-s DESTDIR=/out \
    && cp config.log /sources/wine-build-config.log \
    && cp /src/wine/COPYING.LIB /sources/Wine-COPYING.LIB \
    && tar --no-same-owner -xzf /sources/fex-2510-source-with-submodules.tar.gz -C /src \
    && echo 'f34a779f56b36d22b20e1b990d23e583a6a7ca071331925fa46156441c77a1ee  /src/fex/LICENSE' | sha256sum --check \
    && python3 /inputs/fetch_inputs.py --lock /inputs/sources.lock.json --notices /src/fex --notice-output /sources/fex-notices \
    && for arch in arm64ec aarch64; do \
         PATH=/toolchain/bin:$PATH cmake -S /src/fex -B /fex-$arch -GNinja -DCMAKE_BUILD_TYPE=Release \
           -DCMAKE_TOOLCHAIN_FILE=/src/fex/Data/CMake/toolchain_mingw.cmake \
           -DMINGW_TRIPLE=$arch-w64-mingw32 -DENABLE_LTO=False -DBUILD_TESTING=False \
           -DENABLE_JEMALLOC_GLIBC_ALLOC=False -DTUNE_CPU=none -DTUNE_ARCH=generic \
           -DCMAKE_INSTALL_PREFIX=/opt/wine -DCMAKE_INSTALL_LIBDIR=lib/wine/aarch64-windows \
           -DOVERRIDE_VERSION=2510 \
         && PATH=/toolchain/bin:$PATH cmake --build /fex-$arch --parallel 2 \
         && cp /fex-$arch/Bin/lib*fex.dll /out/opt/wine/lib/wine/aarch64-windows/ \
         && cp /fex-$arch/CMakeCache.txt /sources/fex-$arch-CMakeCache.txt || exit 1; \
       done \
    && dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n' > /sources/build-packages.tsv \
    && cd / && rm -rf /toolchain /src /wine-build /fex-arm64ec /fex-aarch64

FROM base AS runtime
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends \
      ca-certificates python3 tigervnc-standalone-server xauth xfonts-base \
      libgl1-mesa-dri libglx-mesa0 libgl1 libvulkan1 mesa-vulkan-drivers \
      libx11-6 libxext6 libxrender1 libxrandr2 libxi6 libxfixes3 libxcursor1 libxinerama1 \
      libxxf86vm1 libxcomposite1 libxdamage1 libfontconfig1 libfreetype6 fonts-liberation \
      libasound2 libpulse0 libdbus-1-3 libudev1 libgnutls30 libunwind8 procps \
    && apt-get clean
COPY --from=builder /out/opt/wine /opt/wine
COPY --from=builder /sources/Wine-COPYING.LIB /usr/share/doc/esteria-wine-arm64/COPYING.LIB
COPY --from=builder /sources/fex-notices /usr/share/doc/esteria-wine-arm64/fex/
COPY --from=builder /sources/toolchain-notices /usr/share/doc/esteria-wine-arm64/toolchain/
RUN python3 /inputs/record_runtime.py --lock /inputs/sources.lock.json --output /etc/esteria-wine-arm64.json \
    && rm -rf /var/lib/apt/lists/* /var/log/*
CMD ["/opt/wine/bin/wine", "--version"]

FROM runtime AS private-image-test
COPY --from=builder /private-pe-fixtures /private-pe-fixtures
RUN --network=none python3 /private-pe-fixtures/private_pe_check.py --wine /opt/wine/bin/wine \
      --wineserver /opt/wine/bin/wineserver --exe /private-pe-fixtures/private-pe-check.exe \
      --dll /private-pe-fixtures/private-pe-fixture.dll --output /private-pe-evidence
FROM scratch AS private-image-test-export
COPY --from=private-image-test /private-pe-evidence/ /

FROM builder AS corresponding-sources
COPY --from=runtime /etc/esteria-wine-arm64.json /sources/runtime.json
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    python3 /inputs/capture_sources.py --runtime /sources/runtime.json --build-packages /sources/build-packages.tsv \
      --lock /inputs/sources.lock.json --ca /run/secrets/build_ca --output /package-sources \
    && python3 /inputs/capture_toolchain_sources.py --lock /inputs/sources.lock.json \
      --ca /run/secrets/build_ca --output /sources/toolchain-sources
FROM scratch AS source-export
COPY --from=corresponding-sources /sources/ /wine/
COPY --from=corresponding-sources /package-sources/ /debian/
