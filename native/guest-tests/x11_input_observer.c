/* SPDX-License-Identifier: GPL-3.0-only
 * Actual X11 observer for the production helper. Never calls XTest itself.
 */
#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static Display *display;
static Window window;
static unsigned events, acknowledgments;
static int failed(const char *reason) { fprintf(stderr, "X11_INPUT_FAILURE %s\n", reason); return 0; }
#define CHECK(test, reason) do { if (!(test)) return failed(reason); } while (0)
static int64_t millis(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
static int exchange_bytes(int fd, void *data, size_t length, int writing) {
    unsigned char *cursor = data;
    while (length) {
        ssize_t count = writing ? send(fd, cursor, length, MSG_NOSIGNAL) : recv(fd, cursor, length, 0);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return 0;
        cursor += count; length -= (size_t)count;
    }
    return 1;
}
static int connect_helper(const char *path) {
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    if (strlen(path) >= sizeof(address.sun_path)) return -1;
    strcpy(address.sun_path, path);
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    struct timeval timeout = {.tv_sec = 3};
    if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) ||
        connect(fd, (void *)&address, sizeof(address))) { close(fd); return -1; }
    char greeting[8];
    if (!exchange_bytes(fd, greeting, sizeof(greeting), 0) || memcmp(greeting, "ESTRIN01", 8)) { close(fd); return -1; }
    return fd;
}
static int command(int fd, unsigned type, int x, int y, unsigned mask, unsigned expected) {
    uint32_t wire[] = {htonl(type), htonl((uint32_t)x), htonl((uint32_t)y), htonl(mask)}, reply;
    CHECK(exchange_bytes(fd, wire, sizeof(wire), 1) && exchange_bytes(fd, &reply, sizeof(reply), 0), "command-transport");
    CHECK(ntohl(reply) == expected, "command-ack-status"); acknowledgments++; return 1;
}
/* Synchronizing the helper's X connection does not enqueue events on this
 * connection until we read. Poll the actual X fd with a bounded deadline. */
static int next_event(XEvent *event, int timeout) {
    int64_t deadline = millis() + timeout;
    while (!XPending(display)) {
        int remaining = (int)(deadline - millis());
        if (remaining <= 0) return 0;
        struct pollfd fd = {.fd = ConnectionNumber(display), .events = POLLIN};
        int count = poll(&fd, 1, remaining);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0 || !(fd.revents & POLLIN)) return 0;
    }
    XNextEvent(display, event); return 1;
}
static int observe(int type, unsigned detail, int root_x, int root_y, char text) {
    XEvent event;
    CHECK(next_event(&event, 3000), "missing-window-event");
    CHECK(event.type == type && event.xany.window == window && !event.xany.send_event, "wrong-window-event");
    if (type == KeyPress || type == KeyRelease) {
        CHECK(event.xkey.keycode == detail, "wrong-keycode");
        if (text) {
            char buffer[8]; KeySym symbol;
            CHECK(XLookupString(&event.xkey, buffer, sizeof(buffer), &symbol, NULL) == 1 && buffer[0] == text,
                  "wrong-keyboard-text-or-shift");
        }
    } else if (type == ButtonPress || type == ButtonRelease) {
        CHECK(event.xbutton.button == detail, "wrong-button");
    } else if (type == MotionNotify) {
        CHECK(event.xmotion.x_root == root_x && event.xmotion.y_root == root_y, "wrong-motion");
    }
    events++; return 1;
}
static int pointer(int x, int y, unsigned buttons) {
    Window root, child; int root_x, root_y, local_x, local_y; unsigned mask;
    CHECK(XQueryPointer(display, window, &root, &child, &root_x, &root_y, &local_x, &local_y, &mask), "query-pointer");
    CHECK(root_x == x && root_y == y && (mask & (Button1Mask | Button2Mask | Button3Mask | Button4Mask | Button5Mask)) == buttons,
          "pointer-state"); return 1;
}
static int neutral(KeyCode key) {
    char keys[32]; XQueryKeymap(display, keys);
    CHECK(!(keys[key / 8] & (1 << (key % 8))), "stuck-key");
    CHECK(pointer(113, 93, 0), "stuck-button"); return 1;
}
static int exercise(const char *socket_path) {
    window = XCreateSimpleWindow(display, DefaultRootWindow(display), 10, 10, 600, 440, 0, 0, 0);
    CHECK(window != None, "create-window");
    XSelectInput(display, window, StructureNotifyMask | KeyPressMask | KeyReleaseMask | ButtonPressMask |
                 ButtonReleaseMask | PointerMotionMask);
    XMapWindow(display, window); XSync(display, False);
    XEvent mapped; CHECK(next_event(&mapped, 3000) && mapped.type == MapNotify, "window-map");
    XSetInputFocus(display, window, RevertToParent, CurrentTime); XSync(display, False);
    while (XPending(display)) XNextEvent(display, &mapped);
    KeyCode a = XKeysymToKeycode(display, XK_a), b = XKeysymToKeycode(display, XK_b);
    KeyCode shift = XKeysymToKeycode(display, XK_Shift_L), one = XKeysymToKeycode(display, XK_1);
    CHECK(a && b && shift && one, "required-keyboard-map");
    int fd = connect_helper(socket_path); CHECK(fd >= 0, "connect-helper");
    CHECK(command(fd, 0, 100, 100, 0, 0) && observe(MotionNotify, 0, 100, 100, 0) && pointer(100, 100, 0), "absolute-motion");
    CHECK(command(fd, 1, 13, -7, 0, 0) && observe(MotionNotify, 0, 113, 93, 0) && pointer(113, 93, 0), "relative-motion");
    CHECK(command(fd, 2, 0, 0, 1, 0) && observe(ButtonPress, 1, 0, 0, 0) && pointer(113, 93, Button1Mask), "button-press");
    CHECK(command(fd, 2, 0, 0, 0, 0) && observe(ButtonRelease, 1, 0, 0, 0) && pointer(113, 93, 0), "button-release");
    CHECK(command(fd, 3, XK_a, 1, 0, 0) && observe(KeyPress, a, 0, 0, 'a'), "key-press");
    CHECK(command(fd, 3, XK_a, 0, 0, 0) && observe(KeyRelease, a, 0, 0, 0), "key-release");
    CHECK(command(fd, 3, XK_Shift_L, 1, 0, 0) && observe(KeyPress, shift, 0, 0, 0), "shift-press");
    CHECK(command(fd, 3, XK_1, 1, 0, 0) && observe(KeyPress, one, 0, 0, '!'), "shifted-text");
    CHECK(command(fd, 3, XK_1, 0, 0, 0) && observe(KeyRelease, one, 0, 0, 0), "shifted-release");
    CHECK(command(fd, 3, XK_Shift_L, 0, 0, 0) && observe(KeyRelease, shift, 0, 0, 0), "shift-release");
    CHECK(command(fd, 3, XK_b, 1, 0, 0) && observe(KeyPress, b, 0, 0, 'b'), "held-key");
    CHECK(command(fd, 2, 0, 0, 4, 0) && observe(ButtonPress, 3, 0, 0, 0), "held-button");
    close(fd);
    CHECK(observe(ButtonRelease, 3, 0, 0, 0) && observe(KeyRelease, b, 0, 0, 0) && neutral(b), "release-on-eof");
    fd = connect_helper(socket_path); CHECK(fd >= 0, "reconnect-unsupported");
    CHECK(command(fd, 3, XK_A, 1, 0, 1), "unsupported-shifted-symbol-rejection");
    char extra; CHECK(recv(fd, &extra, 1, 0) == 0, "rejected-stream-must-close"); close(fd);
    CHECK(!next_event(&mapped, 150) && neutral(a), "rejected-symbol-injected-event");
    fd = connect_helper(socket_path); CHECK(fd >= 0, "reconnect-after-rejection");
    CHECK(command(fd, 3, XK_a, 1, 0, 0) && observe(KeyPress, a, 0, 0, 'a'), "recovered-key");
    CHECK(command(fd, 3, XK_a, 0, 0, 0) && observe(KeyRelease, a, 0, 0, 0), "recovered-release");
    close(fd); CHECK(neutral(a) && neutral(b) && neutral(shift), "final-neutral-state");
    CHECK(events == 16 && acknowledgments == 15, "fixture-counts");
    return 1;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    display = XOpenDisplay(NULL);
    if (!display) { failed("open-display"); return 3; }
    int passed = exercise(argv[1]);
    if (window) XDestroyWindow(display, window);
    XCloseDisplay(display);
    if (!passed) return 1;
    FILE *receipt = fopen(argv[2], "wx");
    if (!receipt) return 4;
    const char *json = "{\"formatVersion\":1,\"scope\":\"native-linux-arm64-x11-input-fixture\","
        "\"groupsPassed\":7,\"observedEvents\":16,\"acknowledgments\":15,"
        "\"absoluteMotion\":true,\"relativeMotion\":true,\"buttons\":true,\"keyboardAndShift\":true,"
        "\"releaseOnEof\":true,\"unsupportedKeyRejected\":true,\"reconnectNeutral\":true,"
        "\"androidQualified\":false,\"controllerQualified\":false,\"gameplayQualified\":false}\n";
    if (fputs(json, receipt) < 0 || fclose(receipt)) return 5;
    puts("ESTERIA_X11_INPUT_OBSERVER_PASS"); return 0;
}
