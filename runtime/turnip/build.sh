#!/bin/sh
set -eu
ln -s /src/spirv-tools /src/glslang/External/spirv-tools
ln -s /src/spirv-headers /src/spirv-tools/external/spirv-headers
cmake -S /src/glslang -B /build/glslang -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/tools \
    -DENABLE_OPT=ON -DBUILD_EXTERNAL=ON -DBUILD_TESTING=OFF -DGLSLANG_TESTS=OFF \
    -DENABLE_GLSLANG_BINARIES=ON -DSPIRV_SKIP_TESTS=ON
cmake --build /build/glslang --parallel 2
cmake --install /build/glslang
export PATH="/tools/bin:$PATH"
python3 /src/meson/meson.py setup /build/mesa /src/mesa \
    --prefix=/esteria-turnip --libdir=lib --buildtype=release --wrap-mode=nofallback \
    -Dplatforms=x11 -Dgallium-drivers= -Dvulkan-drivers=freedreno -Dfreedreno-kmds=kgsl \
    -Dglx=disabled -Degl=disabled -Dgbm=disabled -Dopengl=false -Dgles1=disabled -Dgles2=disabled \
    -Dllvm=disabled -Dxmlconfig=enabled -Dzstd=enabled -Dshader-cache=enabled \
    -Dxlib-lease=disabled -Dvideo-codecs= -Dbuild-tests=false \
    -Dvalgrind=disabled -Dlibunwind=disabled -Ddraw-use-llvm=false
python3 /src/meson/meson.py compile -C /build/mesa -j 2
DESTDIR=/installed python3 /src/meson/meson.py install -C /build/mesa --no-rebuild
mkdir -p /out/lib /out/bin /out/notices /out/corresponding-source/build-recipe
cp /installed/esteria-turnip/lib/libvulkan_freedreno.so /out/lib/
cp -L /tools/bin/glslangValidator /out/bin/glslangValidator
cp /tools/bin/spirv-val /out/bin/spirv-val
glslangValidator -V --target-env vulkan1.0 /inputs/probe.vert -o /build/probe.vert.spv
glslangValidator -V --target-env vulkan1.0 /inputs/probe.frag -o /build/probe.frag.spv
python3 /inputs/record_build.py --shader-header
gcc -std=c11 -O2 -Wall -Wextra -Werror -I/build /inputs/probe.c -lvulkan -ldl -o /out/bin/esteria-turnip-probe
cp -r /inputs/. /out/corresponding-source/build-recipe/
cp /src/mesa/docs/license.rst /out/notices/MESA-LICENSE.rst
cp -r /src/mesa/licenses /out/notices/MESA-licenses
cp /src/glslang/LICENSE.txt /out/notices/GLSLANG-LICENSE.txt
cp /src/meson/COPYING /out/notices/MESON-COPYING
cp /src/spirv-tools/LICENSE /out/notices/SPIRV-TOOLS-LICENSE
cp /src/spirv-headers/LICENSE /out/notices/SPIRV-HEADERS-LICENSE
python3 /inputs/qualify_shaders.py --directory /out/bin --output /out/shader-tool-check
python3 /inputs/record_build.py --revision "$INTEGRATION_REVISION"
