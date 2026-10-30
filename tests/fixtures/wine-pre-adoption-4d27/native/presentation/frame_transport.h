/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef ESTERIA_FRAME_TRANSPORT_H
#define ESTERIA_FRAME_TRANSPORT_H
#include <errno.h>
#include <sys/socket.h>
#include <stddef.h>
static inline int esteria_receive(int fd, void *storage, size_t bytes) {
    unsigned char *next = storage;
    while (bytes) {
        ssize_t got = recv(fd, next, bytes, 0);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) return -1;
        bytes -= (size_t)got;
        next += got;
    }
    return 0;
}
static inline int esteria_send(int fd, const void *storage, size_t bytes) {
    const unsigned char *next = storage;
    while (bytes) {
        ssize_t sent = send(fd, next, bytes, MSG_NOSIGNAL);
        if (sent < 0 && errno == EINTR) continue;
        if (sent <= 0) return -1;
        bytes -= (size_t)sent;
        next += sent;
    }
    return 0;
}
#endif
