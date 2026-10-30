/* SPDX-License-Identifier: GPL-3.0-only
 * Dedicated Esteria protocol: ESTRIN01 greeting; four network-order words.
 * Types: 0 absolute(x,y,buttons), 1 relative(dx,dy,buttons), 2 buttons(0,0,mask),
 * 3 keysym(keysym,down,0). Reply is one network-order word: 0 accepted, 1 rejected.
 * Keys are physical base-level symbols; text sends explicit Shift/base pairs.
 * Disconnect releases every injected key and button.
 */
#define _POSIX_C_SOURCE 200809L
#include "../presentation/frame_transport.h"
#include "private_socket.h"
#include <X11/Xlib.h>
#include <X11/extensions/XTest.h>
#include <arpa/inet.h>
#include <signal.h>
#include <stdio.h>
#include <stdint.h>
static volatile sig_atomic_t running = 1;
static int xerror;
static void stop(int signum) { (void)signum; running = 0; }
static int x_failure(Display *display, XErrorEvent *event) { (void)display; xerror = event->error_code; return 0; }
static int acknowledge(int fd, unsigned status) { uint32_t value = htonl(status); return esteria_send(fd, &value, sizeof(value)); }
static void buttons(Display *display, unsigned before, unsigned after) {
    for (unsigned bit = 0; bit < 5; ++bit) if ((before ^ after) & (1u << bit))
        XTestFakeButtonEvent(display, bit + 1, (after & (1u << bit)) != 0, CurrentTime);
}
static void consume(Display *display, int fd) {
    unsigned mouse = 0; unsigned char keys[256] = {0}; uint32_t wire[4];
    if (esteria_send(fd, "ESTRIN01", 8)) return;
    while (running) {
        /* A held key or idle menu may produce no events for minutes. Apply a
         * deadline only after a command begins, never to idle key ownership. */
        struct timeval idle = {0};
        (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &idle, sizeof(idle));
        ssize_t first = recv(fd, wire, 1, 0);
        if (first < 0 && errno == EINTR && running) continue;
        if (first != 1 || !running) break;
        private_timeout(fd);
        if (esteria_receive(fd, (unsigned char *)wire + 1, sizeof(wire) - 1)) break;
        uint32_t type = ntohl(wire[0]), state = ntohl(wire[3]);
        int32_t x = (int32_t)ntohl(wire[1]), y = (int32_t)ntohl(wire[2]);
        xerror = 0;
        if (type > 3 || state > 31) { (void)acknowledge(fd, 1); break; }
        if (type == 3) {
            if (state || (y != 0 && y != 1) || x <= 0 || x > 0xffff) { (void)acknowledge(fd, 1); break; }
            KeyCode code = XKeysymToKeycode(display, (KeySym)(uint32_t)x);
            int per_code = 0;
            KeySym *mapping = code ? XGetKeyboardMapping(display, code, 1, &per_code) : NULL;
            int base = mapping && per_code > 0 && mapping[0] == (KeySym)(uint32_t)x;
            if (mapping) XFree(mapping);
            if (!base || xerror) { (void)acknowledge(fd, 1); break; }
            XTestFakeKeyEvent(display, code, y, CurrentTime); keys[code] = (unsigned char)y;
        } else {
            if (x < -4096 || x > 4096 || y < -4096 || y > 4096 || (type == 2 && (x || y))) { (void)acknowledge(fd, 1); break; }
            if (type == 0) XTestFakeMotionEvent(display, DefaultScreen(display), x < 0 ? 0 : x, y < 0 ? 0 : y, CurrentTime);
            if (type == 1) XTestFakeRelativeMotionEvent(display, x, y, CurrentTime);
            buttons(display, mouse, state); mouse = state;
        }
        XSync(display, False);
        if (acknowledge(fd, xerror ? 1u : 0u) || xerror) break;
    }
    buttons(display, mouse, 0);
    for (unsigned code = 0; code < 256; ++code) if (keys[code]) XTestFakeKeyEvent(display, code, False, CurrentTime);
    XSync(display, False);
}
int main(int argc, char **argv) {
    if (argc != 2) { fputs("Usage: esteria-x11-input /private/session/input.sock\n", stderr); return 2; }
    struct sigaction action = {.sa_handler = stop}; sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL); sigaction(SIGINT, &action, NULL); signal(SIGPIPE, SIG_IGN);
    XSetErrorHandler(x_failure);
    Display *display = XOpenDisplay(NULL); int event, error, major, minor;
    if (!display || !XTestQueryExtension(display, &event, &error, &major, &minor)) return 3;
    int listener = private_listener(argv[1]); struct stat owned;
    if (listener < 0 || lstat(argv[1], &owned)) { XCloseDisplay(display); return 4; }
    fputs("ESTERIA_X11_INPUT_READY protocol=1\n", stderr); fflush(stderr);
    while (running) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) { if (errno == EINTR) continue; break; }
        private_timeout(fd); consume(display, fd); close(fd);
    }
    close(listener); int cleaned = private_cleanup(argv[1], &owned); XCloseDisplay(display);
    return cleaned ? 5 : 0;
}
