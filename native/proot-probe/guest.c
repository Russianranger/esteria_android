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
#include <sys/syscall.h>
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
static void exact_file(const char *name, const char *content) {
    int fd = open(name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    require(fd >= 0, "rename persisted file open");
    char value[64]; size_t length = strlen(content);
    require(length < sizeof(value), "rename fixture size");
    transfer(fd, value, length, 0);
    char extra;
    require(!memcmp(value, content, length) && read(fd, &extra, 1) == 0 && close(fd) == 0,
            "rename persisted exact bytes");
}
static void create_file(const char *name, const char *content) {
    int fd = open(name, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    require(fd >= 0, "rename exclusive file create");
    transfer(fd, (void *)content, strlen(content), 1);
    require(fsync(fd) == 0 && close(fd) == 0, "rename file flush");
}
static void rename_check(const char *work, int writing) {
    require(chdir(work) == 0, "rename guest working directory");
    if (writing) {
        create_file("rename-target", "old inode\n");
        int previous = open("rename-target", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        require(previous >= 0, "retain old target descriptor");
        create_file("rename-temporary", "new committed inode\n");
        /* Force the x64 legacy number; libc cannot hide missing compatibility. */
        require(syscall(SYS_rename, "rename-temporary", "rename-target") == 0, "legacy rename replaces existing target");
        char old[sizeof("old inode\n") - 1]; transfer(previous, old, sizeof(old), 0);
        require(!memcmp(old, "old inode\n", sizeof(old)) && close(previous) == 0, "replacement retains old open inode");
        require(access("rename-temporary", F_OK) < 0 && errno == ENOENT, "rename source removed");
        require(syscall(SYS_rename, "rename-target", "rename-target") == 0, "same-path rename is unchanged");
        errno = 0;
        require(syscall(SYS_rename, "missing-source", "rename-target") < 0 && errno == ENOENT, "rename missing source errno");
        create_file("rename-link-source-target", "link destination unchanged\n");
        require(symlink("rename-link-source-target", "rename-link-source") == 0, "rename source symlink");
        create_file("rename-link", "replace me\n");
        require(syscall(SYS_rename, "rename-link-source", "rename-link") == 0, "rename moves symlink itself");
        require(mkdir("rename-old-dir", 0700) == 0 && chdir("rename-old-dir") == 0, "rename current directory setup");
        create_file("retained.txt", "cwd preserved\n");
        require(syscall(SYS_rename, "../rename-old-dir", "../rename-new-dir") == 0, "legacy rename moves cwd");
        char expected[4096], actual[4096];
        int count = snprintf(expected, sizeof(expected), "%s/rename-new-dir", work);
        require(count > 0 && (size_t)count < sizeof(expected) && getcwd(actual, sizeof(actual)) &&
                strcmp(expected, actual) == 0, "renamed cwd remains correct in guest namespace");
        exact_file("retained.txt", "cwd preserved\n");
        require(chdir(work) == 0, "restore work after renamed cwd");
        int directory = open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        require(directory >= 0 && fsync(directory) == 0 && close(directory) == 0, "rename directory durability");
    }
    exact_file("rename-target", "new committed inode\n");
    exact_file("rename-link-source-target", "link destination unchanged\n");
    exact_file("rename-new-dir/retained.txt", "cwd preserved\n");
    char target[64]; ssize_t length = readlink("rename-link", target, sizeof(target));
    require(length == (ssize_t)strlen("rename-link-source-target") &&
            !memcmp(target, "rename-link-source-target", (size_t)length), "renamed symlink persisted unchanged");
    printf("ESTERIA_ANDROID_RENAME_PROBE legacy=1 atomicReplace=1 oldDescriptor=1 missingSourceErrno=1 symlink=1 cwd=1 persistence=%s\n",
           writing ? "write" : "verify");
}
int main(int argc, char **argv) {
    alarm(20); /* Bound a failed socket/child fixture even if the host misses it. */
    if (argc == 4 && strcmp(argv[1], "--child") == 0) return child(argv[2], argv[3]);
    require(argc == 5, "usage: probe WORK PLUGIN GLIBC write|verify");
    require(strcmp(gnu_get_libc_version(), argv[3]) == 0, "parent glibc version");
    require(strcmp(argv[4], "write") == 0 || strcmp(argv[4], "verify") == 0, "persistence mode");
    rename_check(argv[1], strcmp(argv[4], "write") == 0);
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
