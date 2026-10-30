/* SPDX-License-Identifier: GPL-3.0-only
 * Esteria implementation of the documented TRASC full-frame wire protocol.
 * No X11 library or Android API dependency: shared by guest and host tests.
 */
#ifndef ESTERIA_FRAME_PROTOCOL_H
#define ESTERIA_FRAME_PROTOCOL_H
#include <stdint.h>
#include <stddef.h>
#define ESTERIA_FRAME_MAGIC UINT32_C(0x54524631)
#define ESTERIA_MAX_WIDTH 1280u
#define ESTERIA_MAX_HEIGHT 768u
#define ESTERIA_MAX_PIXELS (1280u * 720u)
#define ESTERIA_FRAME_BYTES (ESTERIA_MAX_PIXELS * 4u)
#define ESTERIA_REQUEST_FULL 1u
#define ESTERIA_FRAME_SHARED 1u
#define ESTERIA_FRAME_UNCHANGED 2u
/* Host-order: magic, width, height, row bytes, capture us, sequence, bytes, flags. */
static inline int esteria_frame_valid(const uint32_t h[8]) {
    return h[0] == ESTERIA_FRAME_MAGIC && h[1] && h[1] <= ESTERIA_MAX_WIDTH &&
        h[2] && h[2] <= ESTERIA_MAX_HEIGHT && (uint64_t)h[1] * h[2] <= ESTERIA_MAX_PIXELS &&
        h[3] == h[1] * 4u && h[7] <= (ESTERIA_FRAME_SHARED | ESTERIA_FRAME_UNCHANGED) &&
        h[6] == ((h[7] & ESTERIA_FRAME_UNCHANGED) ? 0u : h[3] * h[2]);
}
static inline void esteria_to_rgba(uint32_t *target, const uint32_t *source, size_t pixels) {
    for (size_t i = 0; i < pixels; ++i) {
        uint32_t pixel = source[i];
        target[i] = UINT32_C(0xff000000) | (pixel & 255u) << 16 | (pixel & 65280u) | (pixel >> 16 & 255u);
    }
}
#endif
