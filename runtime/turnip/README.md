# Isolated Linux ARM64 Turnip/KGSL candidate

This recipe builds an additional Vulkan ICD for the existing Debian12 Wine
runtime. It does not replace that runtime, install into the APK, enable gameplay,
or qualify Adreno/Android execution. The current measured rootfs contains Debian
Mesa22.3.6's DRM driver; its presence is not evidence of Android KGSL support.

The read-only UO reference at `922d0bbc702db2a1f5a46d8dfc14f77a8fdb712c`
(`backend/uo_client_runner.py`, `ClientRuntime.java`) selects a separate Turnip
26.0.0 library and `MESA_VK_WSI_DEBUG=sw`, using Xtigervnc and its native Surface
transport. Esteria reuses that architecture, not the unverified driver bytes.
FTA's inspected client runtime is a mixed-architecture bring-up reference and
does not independently qualify an Adreno path.

Here, **Turnip performs GPU rendering; software WSI copies the resulting pixels
into X11**. The existing frame helper then copies X11 pixels into the Android
Surface. This has CPU/memory-bandwidth costs and is not a zero-copy Android Vulkan
surface. Lavapipe remains a separate software-rendering diagnostic. Neither path
has established full-client frame rate, thermal behavior or Thor gameplay.

The exact official Mesa26.1.4 archive is 77,677,128 bytes, SHA-256
`072705caa9adf4740f1489194b13e278ad959166863b5271fe423a86353c9ab6`,
published in its [release notes](https://docs.mesa3d.org/relnotes/26.1.4.html).
The source table `src/freedreno/common/freedreno_devices.py` includes FD740
chip ID `0x43050a01` for KGSL. `freedreno-kmds=kgsl` with only the Freedreno Vulkan
driver disables libdrm linkage. This is Linux/glibc code using KGSL ioctls directly,
not a Bionic driver loaded through libhybris or an Adrenotools bridge.

`tu_knl_kgsl.cc` requires device, GMEM address, highest-bank-bit and UBWC-mode
properties from the kernel. It optionally opens `/dev/dma_heap/system` or `/dev/ion`
for external-memory FD support. Missing those optional allocators does not itself
reject the GPU. The actual app's `/dev/kgsl-3d0` access, Android SELinux policy,
kernel ioctl behavior, submission, memory coherency and presentation remain
hardware gates. PRoot neither grants these permissions nor provides a GPU emulator.

The source archive and every selected Debian package/source checksum are locked.
The same authenticated Debian snapshot and native ARM64 OCI base as the guest
bridges preserve glibc2.36 compatibility. Meson1.7.2 and glslang14.3.0 are built/run
from exact upstream source commits because Debian12's tools are older than Mesa's
requirements. glslang's optimizer/validator support stays enabled against its
`known_good.json` SPIRV-Tools and SPIRV-Headers commits. The exported standalone
`glslangValidator` and `spirv-val` have their own ELF/hash evidence. A native ARM64
fixture requires valid GLSL compilation with `--spirv-val --spirv-dis`, actual
disassembly, independent SPIR-V validation and rejection of both invalid GLSL and
invalid SPIR-V. Those setup-tool checks do not qualify shaders from missing game
assets. No Meson subproject network fallback is allowed. Two compiler jobs
bound build memory. The build exports original archives, recipe, shaders, project
license, upstream notices and direct package notices; it does not claim source
closure for the entire existing Wine rootfs.

Build locally only on a native ARM64 Docker development host:

```sh
docker build --platform linux/arm64 --target turnip-export \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --build-arg INTEGRATION_REVISION=<exact-integration-sha> \
  --output type=local,dest=/tmp/new-turnip-output runtime/turnip
```

CI checks ELF64/AArch64, required libraries, loader, GLIBC/GLIBCXX ceilings,
actual Meson options and source identities. It loads the exact ICD and asks the
Vulkan loader to enumerate in an environment where `/dev/kgsl-3d0` must be absent.
That receipt must keep hardware, X11 presentation, Android and gameplay false.
The first native ARM64 run `41006180058` at integration `73f694c35ffaa6f0f7f8e9bab9eb30b79c84b5d4`
compiled and linked Mesa's KGSL driver, built the two shader tools, passed their
valid/invalid compiler tests and emitted the build-only receipt. The subsequent
no-GPU loader probe failed; its component log was lost with the failed Docker
layer. CI now exports the completed build first and runs the probe in a separate
network-disabled container, retaining its exact bounded log and false/failure
receipt even on error. The failed first run does not qualify ICD loading or
provide a usable retained binary artifact. A successful no-GPU load is never
Adreno qualification.

The separate `--gpu-readback` probe requires observed Mesa Turnip driver identity,
an integrated Qualcomm740 GPU and a KGSL character device. It compiles/runs the
provided vertex and fragment shaders, draws a full image through a real graphics
queue, waits at most five seconds for completion, invalidates host memory and
checks all4,096 pixels. It only emits a hardware-readback receipt after cleanup.
This is an offscreen component probe, not a Wine/X11/Android/game test. Its
`run_probe.py` supervisor requires the exact build-receipt SHA/revision, verifies
the driver/probe bytes, renders an exclusive private manifest, replaces the
environment (including driver/layer selection), rejects a global loader preload
and bounds/drains output through the outer deadline. Use this wrapper rather than
calling the C probe under an ambient loader environment. Its final receipt binds
the observed result to both measured binaries. CI uses the same wrapper with
`--expect-no-kgsl`; it must not report hardware success.
The build manifest's `/out` ICD path is for CI only; future installation must
render a private manifest for the verified immutable generation. No main Thor
test is requested at this stage.
