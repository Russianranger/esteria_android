# Thor performance and heat plan

This plan covers the work after v26 that targets lower SoC temperature and a higher delivered frame rate on the AYN Thor. Each item records its measured basis, what has shipped and what remains. Host, emulator and Thor evidence are kept separate, as in [STATUS.md](STATUS.md).

## v26 measurements on the Thor

The owner's v26 support ZIP covers 128 s of play at the 60 FPS cap and 1280×720.

| Role | Average of one core | Peak |
| --- | ---: | ---: |
| PRoot tracers (6 processes) | 126.5% | 142.4% |
| Wine client | 61.8% | 81.8% |
| Worldserver | 54.2% | 63.5% |
| Frame helper | 33.8% | 45.1% |
| Xtigervnc | 24.7% | 33.2% |
| Esteria app | 18.0% | 24.5% |
| Wineserver | 14.8% | 25.3% |
| Authserver, MySQL, server helper, Wine services, input helper | 25.5% combined | |

The Adreno 740 averaged 10% busy at 401 MHz and peaked at 55.5 °C. The hottest zones were `socd` at 73.0 °C and CPU zones at 66.5–70.0 °C. Android did not grant sustained performance mode (`sustainedPerformance.applied=false`). Heat and frame rate are therefore limited by CPU work, not GPU work. The largest single cost is the ptrace tracing of every guest system call.

The app posted 3,338 changed frames (26.1 per second) and skipped 1,729 unchanged captures. Each changed frame took 14.7 ms to capture in the guest, 18.5 ms from request to the last pixel received, and 8.3 ms to post on Android. These steps ran one after the other, so the median interval between posted frames was about 34 ms despite the 60 FPS cap. In total, 12.3 GB of pixels passed through the frame socket.

## v27 measurements on the Thor

The owner's v27 support ZIP covers 411 s at the 60 FPS cap with Lumenveil off. The owner reports a steady 60 FPS.

| Role | v26 average | v27 average |
| --- | ---: | ---: |
| PRoot tracers | 126.5% | 24.8% |
| Wine client | 61.8% | 57.8% |
| Worldserver | 54.2% | 50.1% |
| Frame helper | 33.8% | 36.8% |
| Esteria app | 18.0% | 25.3% |
| Xtigervnc | 24.7% | 18.7% |
| Wineserver | 14.8% | 5.7% |

The hottest readable zone was a CPU zone at 63.7 °C, against `socd` at 73.0 °C in v26. The GPU averaged 45% busy, peaked at 66%, and stayed at 401 MHz, as it did in v26. Each changed frame now takes 6.5 ms to capture (14.7 ms in v26) and 1.7 ms to post (8.3 ms). The median interval between posted frames was 19 ms.

## 1. PRoot seccomp acceleration (shipped in v27)

Earlier builds set `PROOT_NO_SECCOMP=1` for every guest process. PRoot then stopped every guest system call twice, including futex waits, reads, writes, polls and memory mappings. V27 leaves seccomp acceleration on. PRoot installs a seccomp filter that stops only the system calls it has to rewrite: those that take paths, sockets, process creation and SysV IPC. Futex, read/write, poll/epoll, sleeps and mmap then run without stopping the tracer. If the kernel refuses the filter, PRoot falls back to full tracing on its own.

Each tracer now also receives `TRASC_PROOT_REPORT=1`. When the filter is active, the pinned PRoot build prints `TRASC PRoot: seccomp acceleration observed` to that component's stderr log. The setting **PRoot acceleration** on the launcher is a fallback switch for the next start and defaults to on. The support bundle records the selected value as `runtime.prootSeccompAcceleration.nextStart`. The Android 13 emulator probe runs both modes with identical guest output, requires the marker in accelerated mode, rejects it in full-tracing mode, and covers forced and graceful ownership cleanup with acceleration on.

The success measure on the Thor is the `role.proot-tracer` CPU figure in `game.lastSession.thermal`, compared at the same frame cap.

## 2. Wine esync (not possible with the current Wine)

The pinned Wine is the bylaws/wine 10.13 ARM64EC fork. Its `server/` and `dlls/ntdll/unix/` sources contain no esync, fsync or ntsync backend. The only match is the ordinary `fsync()` call that flushes files. `WINEESYNC=1` would therefore change nothing.

| Backend | Requirement | Status on the Thor |
| --- | --- | --- |
| ntsync | `/dev/ntsync`, Linux 6.14 or later, plus upstream Wine ntsync code that this 10.13 source does not contain | Snapdragon 8 Gen 2 devices ship a 5.15 kernel, so it is unavailable |
| fsync | `futex_waitv`, Linux 5.16 or later, plus the Proton patchset | Unavailable on a 5.15 kernel |
| esync | eventfd and `/dev/shm`, plus the esync patchset from wine-staging/Proton | Possible, but needs a port and a new Wine provider |

V27 adds `device.kernelRelease` to the support bundle, so the kernel version will be measured, not assumed.

An esync port would require these steps:

- Rebase the esync patchset onto the pinned 10.13 ARM64EC fork.
- Provide a writable `/dev/shm` bind inside PRoot.
- Raise the guest's open-file limit.
- Build and publish a new Wine provider cohort with new exact pins.

Its benefit is bounded by the wineserver's 14.8% of a core, plus the wait latency of client threads. With seccomp acceleration, wineserver requests that use plain read/write on pipes no longer stop the tracer, so part of the esync benefit is already obtained. Decide on the port after v27's tracer and wineserver figures are in.

## 3. Presentation

### Request pipelining (shipped in v27)

At 30 and 60 FPS, the Android side now sends the next frame request as soon as a changed frame's last pixel arrives, before it posts that frame. The guest helper starts its next capture while Android posts, so the frame period drops from roughly capture + transfer + post to capture + transfer. The protocol, the helper and the Wine cohort are unchanged. The guest helper still paces captures to 30 or 60 per second, and an unchanged frame still returns to Android-side pacing and idle backoff. At 24 FPS the helper runs at 30, so Android keeps pacing every request and does not pipeline. The host protocol probe checks that the early request leaves before the post begins, that an outstanding request is not sent twice, and that an unchanged, truncated or invalid reply never pipelines.

Expected effect at the 60 FPS cap: up to about 50 delivered frames per second, limited by the client's own rendering rate, instead of 26. Delivering more frames costs more capture work per second. For a heat comparison, use the 30 FPS cap, where the helper's pacing keeps capture work at or below 30 per second.

### Shared-memory capture (halfway step, not started)

The frame helper and Xtigervnc run under separate PRoot tracers. Each tracer emulates SysV shared memory privately, with a 400 KiB segment limit, so MIT-SHM cannot cross them. A halfway step is to have the helper write each frame into a memfd ring that it passes to Android once with `SCM_RIGHTS`. Android would then swizzle directly from the mapping into the window buffer. That removes the 3.7 MB socket transfer and one full-frame copy per frame. The capture itself (`XGetImage` from Xtigervnc) remains. This changes the pinned guest helper and protocol headers, so it needs a new guest-bridge cohort. It is worth doing only if the zero-copy path below is not feasible on the device.

### Zero-copy presentation (design)

**Today's path.** For each changed frame:

1. Turnip renders the image on the GPU.
2. Mesa's software WSI (`MESA_VK_WSI_DEBUG=sw`) copies it into CPU memory and sends it to Xtigervnc with `PutImage`.
3. The frame helper reads it back with `XGetImage`, composites the cursor, compares it with the previous frame and sends it to the app.
4. The app swizzles it into an `ANativeWindow` buffer.

That is at least five full-frame CPU copies and two 3.7 MB socket transfers per frame. Several of the steps run under PRoot tracers. The frame helper, Xtigervnc, the app and part of the Wine client and tracer figures in the table above come from this path.

**Target path.** The Android app allocates the presentation buffers and the GPU renders straight into them:

1. **Allocation (app).** The app creates three `AHardwareBuffer`s at the render size with `RGBA8`, `GPU_COLOR_OUTPUT | GPU_SAMPLED_IMAGE | COMPOSER_OVERLAY` usage. The first version also adds `CPU_READ_RARELY`, which makes Qualcomm gralloc choose a linear layout whose row stride `AHardwareBuffer_describe` reports. The app obtains each buffer's dma-buf descriptor by sending it to itself with `AHardwareBuffer_sendHandleToUnixSocket` and reading the descriptors with plain `recvmsg`. It then passes the descriptors to the guest over the private presentation socket, together with its own width, height, stride and format record. The guest never parses gralloc's private handle.
2. **Swapchain (guest).** A small Vulkan layer loaded into the Wine client process intercepts `vkCreateXlibSurfaceKHR` for the game window, then `vkCreateSwapchainKHR`, `vkGetSwapchainImagesKHR`, `vkAcquireNextImageKHR` and `vkQueuePresentKHR`. The layer imports each descriptor into Turnip with `VK_EXT_external_memory_dma_buf` and `VK_EXT_image_drm_format_modifier` (linear modifier), and returns those images as the swapchain. It reports only `R8G8B8A8_UNORM`/`SRGB` surface formats, because `AHardwareBuffer` has no public BGRA format. If the client insists on BGRA, the layer keeps its own images and adds one GPU blit per frame, which still removes every CPU copy. Today's environment disables all layers (`VK_LOADER_LAYERS_DISABLE=~all~`), so this layer would be the only one enabled.
3. **Present.** On present, the layer exports a sync file for the rendering work with `VK_KHR_external_semaphore_fd`, or, if Turnip's KGSL backend cannot export one, waits on a fence on the CPU. It then sends the image index and fence to the app. The app calls `ASurfaceTransaction_setBuffer` with that acquire fence on an `ASurfaceControl` created from the game surface (Android 10+). The display hardware scales the buffer to the screen, and the app never touches the pixels.
4. **Release and pacing.** The transaction's completion callback returns each buffer's release fence. The layer's acquire step blocks until a buffer has been released. That paces presentation to the display, and the selected cap applies inside `vkQueuePresentKHR`.
5. **Cursor.** The frame helper keeps watching cursor changes with XFixes, but only sends the cursor image when it changes. The app shows it on a small child `ASurfaceControl` positioned at the pointer, so cursor movement no longer requires a full frame.
6. **Fallback.** Windows that are not Vulkan swapchains (Wine dialogs, startup and error boxes) and any handshake failure keep the current `XGetImage` path. The app switches source per session and records which one ran. A launcher setting keeps the readback path selectable until the Thor has qualified zero-copy.

**Expected effect.** Per frame, the frame helper, Xtigervnc and app costs become near zero, and so does the software-WSI part of the Wine client. In the v26 table the frame helper, Xtigervnc and app rows alone total about 77% of one core. The change also removes tracer time for the X socket traffic and roughly 0.5 GB/s of memory traffic. Latency drops by one capture period.

**Unknowns to settle on the Thor first** (a probe binary, before any app integration):

- Whether Turnip's KGSL backend imports a gralloc dma-buf (`IOCTL_KGSL_GPUOBJ_IMPORT`) from inside the PRoot guest, and renders into it correctly with the linear modifier.
- Whether it can export a sync file, or a CPU fence wait is required.
- Whether winex11 in Wine 10.13 creates the game's Vulkan surface directly on the top-level X window, or on an offscreen window that it copies.
- Whether `AHardwareBuffer_sendHandleToUnixSocket` delivers the dma-buf as its first descriptor on the Thor's gralloc.

**Delivery stages.**

1. A guest probe that imports an app-allocated buffer, clears it on the GPU and has the app present it.
2. The layer with a CPU fence and the linear layout, behind the launcher setting.
3. A sync-file fence and the child cursor surface.
4. A UBWC (compressed) layout if the linear layout costs measurable GPU bandwidth.

The layer is a new guest binary and the helper changes touch pinned sources, so stages 2–3 ship with a new guest-bridge provider cohort. The Android 13 emulator has no KGSL device, so emulator CI can check the protocol and the fallback but not the GPU import. GPU import evidence must come from the Thor.

## 4. Native server outside PRoot (assessed, not planned yet)

Running AzerothCore, the authserver and MySQL as native Android (bionic) programs, as in singlePlayerWow-android under Termux, would remove their tracers entirely. Three costs stand in the way:

- **Executable files.** With `targetSdk 35`, Android does not let an app execute files from its data directory. Termux avoids this by targeting SDK 28. Esteria would have to ship the server binaries as `lib*.so` files in the APK's native library directory, which the 337 MB APK and the separate server-provider updates do not suit.
- **Database and pins.** The pinned server stack is a glibc build of AzerothCore with MySQL 8. A bionic build needs its own reproducible provider with exact source pins. MariaDB, which Termux packages, is not officially supported by AzerothCore.
- **Configuration and saves.** The server configuration, database slots and save ownership checks would need a second launch path.

Seccomp acceleration removes most per-call tracer cost for the server processes too, so measure v27 before choosing this.

## 5. Lumenveil at 60 FPS (analysed, client work not started)

Lumenveil is the source-built client's port of the Lumenveil mod: volumetric fog, sun and moon shafts, night lights, water, wet surfaces and colour grading. It runs as extra full-screen and point passes after the world draws, so its cost is almost all GPU work. With Lumenveil off, the GPU was already 45% busy at 401 MHz in v27.

The default **Quality** is High: the fog march runs at half resolution (640×360 at 1280×720), with 32 fog steps and 24 shaft steps per pixel. Low runs at quarter resolution (320×180) with 16 and 12 steps, about an eighth of the march samples. Each frame also updates the shaft memory (a sun-view shadow map, scattered each frame from one depth pixel in 16), runs a temporal filter, and composites at full resolution from up to 10 inputs. Water, wet surfaces, glow, spell lights (with an asynchronous readback) and cloud shadows add further passes.

The GPU clock did not move from 401 MHz in either bundle. Either the Thor's performance profile or thermal policy caps it, or the governor never needed more at 45% busy. V28 records the KGSL cap, floor, governor and frequency steps, plus the client's `lumenveil` switch, so the next bundle shows which.

Next steps, in order:

1. **Owner test, no build:** with Lumenveil on, set **Video → Lumenveil Fog → Quality** to Low and compare the frame rate.
2. **Client measurement:** GPU timestamp queries around each Lumenveil stage, averaged and written to `Logs/Lumenveil.log` every 10 s. The app then extracts only those numbers into the support bundle; client logs stay private.
3. **Client optimizations, chosen from the measurements:**
   - a Handheld quality level: quarter resolution, fewer steps, a stronger temporal filter;
   - shaft memory, water memory and the sky reference updated every second frame;
   - relaxed precision in the translated shaders, so Adreno can use its faster 16-bit arithmetic;
   - fewer separate render passes, which on a tiled GPU each load and store full targets;
   - a frame-time governor that lowers the march resolution before the frame rate drops.

Steps 2 and 3 change Russianranger/wowdecomp_esteria. They need a new client build, pinned in `runtime/client/stock-renderer-build.lock.json`.

