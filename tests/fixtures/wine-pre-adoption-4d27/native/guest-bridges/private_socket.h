/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef ESTERIA_PRIVATE_SOCKET_H
#define ESTERIA_PRIVATE_SOCKET_H
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
/* No stale-path deletion. The session owner must finish the previous generation first. */
static int private_listener(const char *path) {
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    size_t length = strlen(path);
    if (!length || path[0] != '/' || length >= sizeof(address.sun_path)) { errno = EINVAL; return -1; }
    char parent[sizeof(address.sun_path)];
    memcpy(parent, path, length + 1);
    char *slash = strrchr(parent, '/');
    if (!slash || slash == parent) { errno = EINVAL; return -1; }
    *slash = 0;
    struct stat directory;
    if (lstat(parent, &directory) || !S_ISDIR(directory.st_mode) || (directory.st_mode & 0077)) { errno = EACCES; return -1; }
    struct stat existing;
    if (!lstat(path, &existing) || errno != ENOENT) { errno = EEXIST; return -1; }
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    memcpy(address.sun_path, path, length + 1);
    umask(0077);
    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) || listen(fd, 4)) { close(fd); return -1; }
    return fd;
}
static void private_timeout(int fd) {
    struct timeval timeout = {.tv_sec = 2};
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
}
static int private_cleanup(const char *path, const struct stat *owned) {
    struct stat current;
    if (lstat(path, &current)) return errno == ENOENT ? 0 : -1;
    if (!S_ISSOCK(current.st_mode) || current.st_dev != owned->st_dev || current.st_ino != owned->st_ino) return -1;
    return unlink(path);
}
#endif
