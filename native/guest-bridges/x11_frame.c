/* SPDX-License-Identifier: GPL-3.0-only
 * Full-frame TRASC wire compatibility, implemented for Esteria. Local X11
 * readback is deliberately explicit; this is not Android Vulkan presentation.
 */
#define _POSIX_C_SOURCE 200809L
#include "../presentation/frame_protocol.h"
#include "../presentation/frame_transport.h"
#include "private_socket.h"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xfixes.h>
#include <arpa/inet.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static volatile sig_atomic_t running = 1;
static int xerror;
static void stop(int signum) { (void)signum; running = 0; }
static int x_failure(Display *display, XErrorEvent *error) { (void)display; xerror = error->error_code; return 0; }
static uint64_t nanos(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * UINT64_C(1000000000) + (uint64_t)now.tv_nsec;
}
static void overlay_cursor(uint32_t *pixels, uint32_t width, uint32_t height, const XFixesCursorImage *cursor) {
    if (!cursor) return;
    int left = cursor->x - cursor->xhot, top = cursor->y - cursor->yhot;
    unsigned start_x = left < 0 ? (unsigned)-left : 0, start_y = top < 0 ? (unsigned)-top : 0;
    unsigned end_x = left + cursor->width > (int)width ? (unsigned)((int)width - left) : cursor->width;
    unsigned end_y = top + cursor->height > (int)height ? (unsigned)((int)height - top) : cursor->height;
    if (left >= (int)width || top >= (int)height || start_x >= end_x || start_y >= end_y) return;
    for (unsigned y = start_y; y < end_y; ++y) for (unsigned x = start_x; x < end_x; ++x) {
        int dx = cursor->x - cursor->xhot + (int)x, dy = cursor->y - cursor->yhot + (int)y;
        if (dx < 0 || dy < 0 || dx >= (int)width || dy >= (int)height) continue;
        uint32_t argb = (uint32_t)cursor->pixels[y * cursor->width + x], alpha = argb >> 24;
        uint32_t *target = pixels + (size_t)dy * width + (unsigned)dx, before = *target, blended = 0;
        for (unsigned shift = 0; shift < 24; shift += 8) {
            unsigned value = (argb >> shift & 255u) + ((before >> shift & 255u) * (255u - alpha) + 127u) / 255u;
            blended |= (value > 255u ? 255u : value) << shift;
        }
        *target = blended;
    }
}
static int consume(Display *display, int fd, unsigned fps) {
    uint32_t *pixels = malloc(ESTERIA_FRAME_BYTES), *previous = malloc(ESTERIA_FRAME_BYTES);
    if (!pixels || !previous) { free(pixels); free(previous); return -1; }
    uint32_t sequence = 0, last_width = 0, last_height = 0;
    uint64_t last = 0;
    int result = 0;
    while (running) {
        unsigned char request;
        if (esteria_receive(fd, &request, 1)) break;
        if (request != ESTERIA_REQUEST_FULL) { result = -1; break; }
        uint64_t now = nanos(), interval = UINT64_C(1000000000) / fps;
        if (last && now - last < interval) {
            struct timespec delay = {.tv_nsec = (long)(interval - (now - last))};
            while (running && nanosleep(&delay, &delay) && errno == EINTR) { }
        }
        if (!running) break;
        last = nanos(); xerror = 0;
        XWindowAttributes attributes;
        if (!XGetWindowAttributes(display, DefaultRootWindow(display), &attributes)) { result = -1; break; }
        uint32_t h[8] = {ESTERIA_FRAME_MAGIC, (uint32_t)attributes.width, (uint32_t)attributes.height,
            (uint32_t)attributes.width * 4u, 0, ++sequence, (uint32_t)attributes.width * (uint32_t)attributes.height * 4u, 0};
        if (!esteria_frame_valid(h)) { result = -1; break; }
        uint64_t began = nanos();
        XImage *image = XGetImage(display, DefaultRootWindow(display), 0, 0, h[1], h[2], AllPlanes, ZPixmap);
        if (!image || xerror || image->bits_per_pixel != 32 || image->byte_order != LSBFirst ||
                image->red_mask != 0xff0000 || image->green_mask != 0xff00 || image->blue_mask != 0xff ||
                image->bytes_per_line < (int)h[3]) {
            if (image) XDestroyImage(image);
            result = -1; break;
        }
        for (uint32_t row = 0; row < h[2]; ++row)
            memcpy(pixels + (size_t)row * h[1], image->data + (size_t)row * (size_t)image->bytes_per_line, h[3]);
        XDestroyImage(image);
        XFixesCursorImage *cursor = XFixesGetCursorImage(display);
        if (!cursor || xerror) { if (cursor) XFree(cursor); result = -1; break; }
        overlay_cursor(pixels, h[1], h[2], cursor); XFree(cursor);
        h[4] = (uint32_t)((nanos() - began) / 1000u);
        if (last_width == h[1] && last_height == h[2] && !memcmp(previous, pixels, h[6])) {
            h[6] = 0; h[7] = ESTERIA_FRAME_UNCHANGED;
        } else {
            memcpy(previous, pixels, h[6]); last_width = h[1]; last_height = h[2];
        }
        uint32_t wire[8]; for (unsigned i = 0; i < 8; ++i) wire[i] = htonl(h[i]);
        if (esteria_send(fd, wire, sizeof(wire)) || esteria_send(fd, pixels, h[6])) break;
    }
    free(pixels); free(previous); return result;
}
int main(int argc, char **argv) {
    if (argc != 3 || (strcmp(argv[2], "30") && strcmp(argv[2], "60"))) {
        fputs("Usage: esteria-x11-frame /private/session/frame.sock 30|60\n", stderr); return 2;
    }
    struct sigaction action = {.sa_handler = stop}; sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL); sigaction(SIGINT, &action, NULL);
    signal(SIGPIPE, SIG_IGN); XSetErrorHandler(x_failure);
    Display *display = XOpenDisplay(NULL);
    int event, error;
    if (!display || !XFixesQueryExtension(display, &event, &error)) { fputs("X11/XFixes unavailable\n", stderr); return 3; }
    int listener = private_listener(argv[1]); struct stat owned;
    if (listener < 0 || lstat(argv[1], &owned)) { fputs("Private frame endpoint unavailable\n", stderr); XCloseDisplay(display); return 4; }
    fputs("ESTERIA_X11_FRAME_READY protocol=full-v1 capture=XGetImage\n", stderr); fflush(stderr);
    while (running) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) { if (errno == EINTR) continue; break; }
        private_timeout(fd);
        if (consume(display, fd, (unsigned)atoi(argv[2]))) fputs("Frame stream rejected\n", stderr);
        close(fd);
    }
    close(listener); int cleaned = private_cleanup(argv[1], &owned); XCloseDisplay(display);
    return cleaned ? 5 : 0;
}
