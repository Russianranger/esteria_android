/* SPDX-License-Identifier: GPL-3.0-only */
#define _POSIX_C_SOURCE 200809L
#include "frame_protocol.h"
#include "frame_transport.h"
#include <jni.h>
#include <android/native_window_jni.h>
#include <arpa/inet.h>
#include <time.h>

struct frame_cache { uint32_t magic, width, height, sequence; };
static uint64_t clock_ns(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * UINT64_C(1000000000) + (uint64_t)now.tv_nsec;
}
JNIEXPORT jint JNICALL
Java_io_github_russianranger_esteria_presentation_SurfaceBridge_receiveFrame(
        JNIEnv *env, jclass type, jobject surface, jint fd, jobject storage, jlongArray measurements) {
    (void)type;
    if (!storage || !measurements || (*env)->GetArrayLength(env, measurements) < 6) return -1;
    unsigned char *pixels = (*env)->GetDirectBufferAddress(env, storage);
    jlong capacity = (*env)->GetDirectBufferCapacity(env, storage);
    if (!pixels || capacity < (jlong)(ESTERIA_FRAME_BYTES + sizeof(struct frame_cache))) return -1;
    struct frame_cache *cache = (struct frame_cache *)(pixels + ESTERIA_FRAME_BYTES);
    unsigned char request = ESTERIA_REQUEST_FULL;
    uint32_t header[8];
    uint64_t began = clock_ns();
    if (esteria_send(fd, &request, 1) || esteria_receive(fd, header, sizeof(header))) return -2;
    for (unsigned i = 0; i < 8; ++i) header[i] = ntohl(header[i]);
    if (!esteria_frame_valid(header)) return -3;
    int baseline = cache->magic == ESTERIA_FRAME_MAGIC;
    if (baseline && header[5] != cache->sequence + 1u) return -3;
    if (header[7] & ESTERIA_FRAME_UNCHANGED) {
        if (!baseline || header[1] != cache->width || header[2] != cache->height) return -3;
        cache->sequence = header[5];
        return 1;
    }
    if (esteria_receive(fd, pixels, header[6])) return -2;
    uint64_t received = clock_ns();
    ANativeWindow *window = ANativeWindow_fromSurface(env, surface);
    if (!window) return -4;
    int result = 0;
    if (!baseline || cache->width != header[1] || cache->height != header[2])
        result = ANativeWindow_setBuffersGeometry(window, (int32_t)header[1], (int32_t)header[2], WINDOW_FORMAT_RGBA_8888);
    ANativeWindow_Buffer buffer;
    if (!result) {
        result = ANativeWindow_lock(window, &buffer, NULL);
        if (!result) {
            if (!buffer.bits || buffer.width != (int32_t)header[1] || buffer.height != (int32_t)header[2] ||
                    buffer.stride < buffer.width || buffer.format != WINDOW_FORMAT_RGBA_8888) result = -1;
            else for (uint32_t row = 0; row < header[2]; ++row)
                esteria_to_rgba((uint32_t *)buffer.bits + (size_t)row * (size_t)buffer.stride,
                        (const uint32_t *)pixels + (size_t)row * header[1], header[1]);
            int posted = ANativeWindow_unlockAndPost(window);
            if (!result) result = posted;
        }
    }
    ANativeWindow_release(window);
    if (result) return -4;
    cache->magic = ESTERIA_FRAME_MAGIC;
    cache->width = header[1]; cache->height = header[2]; cache->sequence = header[5];
    jlong stats[6] = {header[1], header[2], (jlong)header[4] * 1000,
        (jlong)(received - began), (jlong)(clock_ns() - received), header[6]};
    (*env)->SetLongArrayRegion(env, measurements, 0, 6, stats);
    return (*env)->ExceptionCheck(env) ? -1 : 0;
}
