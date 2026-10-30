/* SPDX-License-Identifier: GPL-3.0-only */
/* Diagnostic Linux glibc program. This is not a game/server readiness check. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <gnu/libc-version.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static void require(int ok, const char *what) {
    if (!ok) { fprintf(stderr, "probe failure: %s: %s\n", what, strerror(errno)); exit(70); }
}
static void transfer(int fd, void *buffer, size_t length, int writing) {
    char *cursor = buffer;
    while (length) {
        ssize_t count = writing ? write(fd, cursor, length) : read(fd, cursor, length);
        if (count < 0 && errno == EINTR) continue;
        require(count > 0, "short I/O"); cursor += count; length -= (size_t)count;
    }
}
typedef int (*tls_function)(void);
static void *thread_check(void *argument) {
    tls_function function = *(tls_function *)argument;
    return (void *)(long)(function() == 42 && function() == 43);
}
static int child(const char *port_text, const char *version) {
    require(strcmp(gnu_get_libc_version(), version) == 0, "child glibc version");
    char *end; long port = strtol(port_text, &end, 10);
    require(*end == 0 && port > 0 && port <= 65535, "child port");
    int socket_fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    require(socket_fd >= 0, "child socket");
    struct sockaddr_in address = {.sin_family=AF_INET, .sin_port=htons((unsigned short)port)};
    require(inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1, "loopback address");
    require(connect(socket_fd, (struct sockaddr *)&address, sizeof(address)) == 0, "loopback connect");
    char message[] = "esteria-child-exec";
    transfer(socket_fd, message, sizeof(message), 1);
    char reply[3]; transfer(socket_fd, reply, sizeof(reply), 0);
    require(memcmp(reply, "ok", sizeof(reply)) == 0, "loopback response");
    require(close(socket_fd) == 0, "child socket close"); return 17;
}
int main(int argc, char **argv) {
    alarm(20); /* Bound a failed socket/child fixture even if the host misses it. */
    if (argc == 4 && strcmp(argv[1], "--child") == 0) return child(argv[2], argv[3]);
    require(argc == 5, "usage: probe WORK PLUGIN GLIBC write|verify");
    require(strcmp(gnu_get_libc_version(), argv[3]) == 0, "parent glibc version");
    require(strcmp(argv[4], "write") == 0 || strcmp(argv[4], "verify") == 0, "persistence mode");
    void *library = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
    require(library != NULL, "dlopen");
    tls_function function = (tls_function)dlsym(library, "esteria_probe_tls");
    require(function != NULL && function() == 42, "dlsym/TLS main");
    pthread_t thread; void *thread_result = NULL;
    require(pthread_create(&thread, NULL, thread_check, &function) == 0, "pthread create");
    require(pthread_join(thread, &thread_result) == 0 && thread_result == (void *)1, "thread-local dynamic code");
    require(function() == 43 && dlclose(library) == 0, "independent TLS and dlclose");
    char path[4096];
    int length = snprintf(path, sizeof(path), "%s/persistent-probe.txt", argv[1]);
    require(length > 0 && (size_t)length < sizeof(path), "work path");
    char persisted[] = "esteria-local-runtime-persistence\n";
    if (strcmp(argv[4], "write") == 0) {
        int output = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
        require(output >= 0, "exclusive persistent file"); transfer(output, persisted, sizeof(persisted)-1, 1);
        require(fsync(output) == 0 && close(output) == 0, "persistent flush");
    }
    int input = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW); require(input >= 0, "persistent read");
    char restored[sizeof(persisted)-1]; transfer(input, restored, sizeof(restored), 0);
    require(memcmp(restored, persisted, sizeof(restored)) == 0, "persistent content");
    char extra; require(read(input, &extra, 1) == 0 && close(input) == 0, "persistent exact length");
    int listener = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0); require(listener >= 0, "listen socket");
    struct sockaddr_in address = {.sin_family=AF_INET, .sin_addr={htonl(INADDR_LOOPBACK)}, .sin_port=0};
    require(bind(listener, (struct sockaddr *)&address, sizeof(address)) == 0 && listen(listener, 1) == 0, "loopback bind");
    socklen_t size = sizeof(address); require(getsockname(listener, (struct sockaddr *)&address, &size) == 0, "chosen port");
    char port[6]; snprintf(port, sizeof(port), "%u", (unsigned)ntohs(address.sin_port));
    pid_t pid = fork(); require(pid >= 0, "fork");
    if (pid == 0) { execl(argv[0], argv[0], "--child", port, argv[3], (char *)NULL); _exit(71); }
    int accepted = accept4(listener, NULL, NULL, SOCK_CLOEXEC); require(accepted >= 0, "loopback accept");
    char message[sizeof("esteria-child-exec")]; transfer(accepted, message, sizeof(message), 0);
    require(memcmp(message, "esteria-child-exec", sizeof(message)) == 0, "executed child message");
    char reply[] = "ok"; transfer(accepted, reply, sizeof(reply), 1);
    require(close(accepted) == 0 && close(listener) == 0, "parent socket close");
    int status; require(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && WEXITSTATUS(status) == 17, "child exit status");
    printf("ESTERIA_ANDROID_GLIBC_PROBE glibc=%s dlopen=1 tls=1 fork=1 exec=1 loopback=1 persistence=%s childExit=17\n", gnu_get_libc_version(), argv[4]);
    return 0;
}
