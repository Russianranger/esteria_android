/* SPDX-License-Identifier: GPL-3.0-only
 * Test-only Linux/glibc stat fixture. Never part of a production runtime. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static const char *primary, *alias;
static int first_observation;
static void need(int ok, const char *what) {
    if (!ok) { fprintf(stderr, "stat fixture: %s: %s\n", what, strerror(errno)); exit(70); }
}
static void path(char out[4096], const char *root, const char *relative) {
    int length = snprintf(out, 4096, "%s%s%s", root, *relative ? "/" : "", relative);
    need(length > 0 && length < 4096, "path bound");
}
static void pause_clock(void) {
    struct timespec remaining = {0, 20000000};
    while (nanosleep(&remaining, &remaining) < 0) need(errno == EINTR, "clock pause");
}
static int64_t nanoseconds(struct timespec value) {
    need(value.tv_sec >= 0 && value.tv_sec <= INT64_MAX / 1000000000 && value.tv_nsec >= 0 && value.tv_nsec < 1000000000,
         "timestamp range");
    return (int64_t)value.tv_sec * INT64_C(1000000000) + value.tv_nsec;
}
static int equal(const struct stat *a, const struct stat *b) {
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_mode == b->st_mode &&
        a->st_uid == b->st_uid && a->st_gid == b->st_gid && a->st_nlink == b->st_nlink &&
        a->st_size == b->st_size && nanoseconds(a->st_mtim) == nanoseconds(b->st_mtim) &&
        nanoseconds(a->st_ctim) == nanoseconds(b->st_ctim);
}
static void emit_stat(const struct stat *value) {
    printf("{\"dev\":\"%ju\",\"ino\":\"%ju\",\"mode\":\"%ju\",\"uid\":\"%ju\",\"gid\":\"%ju\",\"nlink\":\"%ju\",\"size\":\"%jd\",\"mtimeNs\":\"%" PRId64 "\",\"ctimeNs\":\"%" PRId64 "\"}",
        (uintmax_t)value->st_dev, (uintmax_t)value->st_ino, (uintmax_t)value->st_mode,
        (uintmax_t)value->st_uid, (uintmax_t)value->st_gid, (uintmax_t)value->st_nlink,
        (intmax_t)value->st_size, nanoseconds(value->st_mtim), nanoseconds(value->st_ctim));
}
static struct stat capture(const char *relative, int follow) {
    char a[4096], b[4096]; struct stat libc_a, libc_b, raw_a, raw_b;
    path(a, primary, relative); path(b, alias, relative);
    need((follow ? stat(a, &libc_a) : lstat(a, &libc_a)) == 0, "libc primary stat");
    need((follow ? stat(b, &libc_b) : lstat(b, &libc_b)) == 0, "libc alias stat");
    int flags = follow ? 0 : AT_SYMLINK_NOFOLLOW;
    need(syscall(SYS_newfstatat, AT_FDCWD, a, &raw_a, flags) == 0, "raw primary fstatat");
    need(syscall(SYS_newfstatat, AT_FDCWD, b, &raw_b, flags) == 0, "raw alias fstatat");
    need(equal(&libc_a, &libc_b) && equal(&libc_a, &raw_a) && equal(&libc_a, &raw_b), "stable alias/syscall tuples");
    printf("{\"work\":"); emit_stat(&libc_a); printf(",\"data\":"); emit_stat(&libc_b);
    printf(",\"rawWork\":"); emit_stat(&raw_a); printf(",\"rawData\":"); emit_stat(&raw_b); printf("}");
    return libc_a;
}
static struct stat observe(const char *label, const char *relative, int follow) {
    if (!first_observation) { printf(","); }
    first_observation = 0;
    printf("\"%s\":", label); return capture(relative, follow);
}
static void write_exact(const char *relative, const char *bytes, int exclusive) {
    char file[4096]; path(file, primary, relative);
    int fd = open(file, O_WRONLY | O_CLOEXEC | O_NOFOLLOW | (exclusive ? O_CREAT | O_EXCL : 0), 0600);
    need(fd >= 0, "owned fixture file open"); size_t count = 0, length = strlen(bytes);
    while (count < length) { ssize_t wrote = write(fd, bytes + count, length - count); need(wrote > 0, "fixture write"); count += (size_t)wrote; }
    need(fsync(fd) == 0 && close(fd) == 0, "fixture flush");
}
static void restore_time(const char *relative, const struct stat *before) {
    char file[4096]; path(file, primary, relative);
    struct timespec times[2] = {before->st_atim, before->st_mtim};
    need(utimensat(AT_FDCWD, file, times, AT_SYMLINK_NOFOLLOW) == 0, "restore original mtime");
}
static void mutation(void) {
    char file[4096], other[4096];
    write_exact("receipt.json", "stat fixture metadata\n", 1);
    write_exact("data/regular.bin", "AAAAAAAA", 1);
    struct stat initial = observe("regularInitial", "data/regular.bin", 0);
    need(S_ISREG(initial.st_mode) && initial.st_size == 8 && initial.st_nlink == 1, "regular fixture");
    path(file, primary, "data/regular.bin"); path(other, primary, "data/hardlink");
    pause_clock(); need(link(file, other) == 0, "hardlink mutation");
    struct stat linked = observe("hardlinkAdded", "data/regular.bin", 0);
    need(linked.st_ino == initial.st_ino && linked.st_nlink == 2 &&
         nanoseconds(linked.st_ctim) != nanoseconds(initial.st_ctim), "hardlink count observed");
    pause_clock(); need(unlink(other) == 0, "hardlink removal");
    struct stat unlinked = observe("hardlinkRemoved", "data/regular.bin", 0);
    need(unlinked.st_ino == initial.st_ino && unlinked.st_nlink == 1 &&
         nanoseconds(unlinked.st_ctim) != nanoseconds(linked.st_ctim), "hardlink removal observed");
    pause_clock(); need(chmod(file, 0400) == 0, "chmod mutation");
    struct stat changed = observe("modeChanged", "data/regular.bin", 0);
    need((changed.st_mode & 0777) == 0400 && changed.st_mode != initial.st_mode, "mode observed");
    pause_clock(); need(chmod(file, 0600) == 0, "restore readable fixture"); observe("modeRestored", "data/regular.bin", 0);
    struct timespec fixed[2] = {{1700000000, 123456789}, {1700000000, 123456789}};
    need(utimensat(AT_FDCWD, file, fixed, 0) == 0, "nanosecond mtime set");
    struct stat before_write = observe("mtimeFixed", "data/regular.bin", 0);
    need(before_write.st_mtim.tv_nsec == 123456789, "nanosecond mtime precision");
    pause_clock(); write_exact("data/regular.bin", "BBBBBBBB", 0); restore_time("data/regular.bin", &before_write);
    struct stat rewritten = observe("rewritten", "data/regular.bin", 0);
    need(before_write.st_size == rewritten.st_size && nanoseconds(before_write.st_mtim) == nanoseconds(rewritten.st_mtim) &&
         nanoseconds(before_write.st_ctim) != nanoseconds(rewritten.st_ctim), "same length restored-mtime write changes ctime");
    int retained = open(file, O_RDONLY | O_CLOEXEC | O_NOFOLLOW); need(retained >= 0, "retained old inode");
    pause_clock(); write_exact("data/replacement", "BBBBBBBB", 1); restore_time("data/replacement", &rewritten);
    path(other, primary, "data/replacement"); need(rename(other, file) == 0, "same-content inode replacement");
    struct stat replaced = observe("replaced", "data/regular.bin", 0);
    need(replaced.st_size == rewritten.st_size && nanoseconds(replaced.st_mtim) == nanoseconds(rewritten.st_mtim) &&
         replaced.st_ino != rewritten.st_ino, "replacement identity observed");
    struct stat old; need(fstat(retained, &old) == 0 && old.st_ino == rewritten.st_ino && close(retained) == 0, "old descriptor identity retained");
    path(file, primary, "data/entries"); need(mkdir(file, 0700) == 0, "entry directory");
    struct stat dir_initial = observe("directoryInitial", "data/entries", 0);
    pause_clock(); write_exact("data/entries/added", "entry", 1); restore_time("data/entries", &dir_initial);
    struct stat added = observe("directoryAdded", "data/entries", 0);
    need(nanoseconds(dir_initial.st_mtim) == nanoseconds(added.st_mtim) && nanoseconds(dir_initial.st_ctim) != nanoseconds(added.st_ctim),
         "added entry visible despite restored directory mtime");
    pause_clock(); path(other, primary, "data/entries/added"); need(unlink(other) == 0, "remove directory entry"); restore_time("data/entries", &dir_initial);
    struct stat removed = observe("directoryRemoved", "data/entries", 0);
    need(nanoseconds(added.st_mtim) == nanoseconds(removed.st_mtim) && nanoseconds(added.st_ctim) != nanoseconds(removed.st_ctim),
         "removed entry visible despite restored directory mtime");
    path(file, primary, "data/symbolic"); need(symlink("regular.bin", file) == 0, "terminal symlink");
    struct stat link = observe("symlink", "data/symbolic", 0); need(S_ISLNK(link.st_mode), "lstat exposes symlink");
    struct stat target = observe("symlinkTarget", "data/symbolic", 1); need(target.st_ino == replaced.st_ino, "stat follows fixture symlink");
    path(file, primary, "data/ancestor"); need(symlink(".", file) == 0, "symlink ancestor");
    struct stat ancestor = observe("ancestor", "data/ancestor", 0); need(S_ISLNK(ancestor.st_mode), "ancestor lstat exposes symlink");
    struct stat leaf = observe("ancestorLeaf", "data/ancestor/regular.bin", 0); need(leaf.st_ino == replaced.st_ino, "leaf stat alone follows symlink ancestor");
    errno = 0; int forbidden = open(file, O_DIRECTORY | O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    need(forbidden < 0 && (errno == ELOOP || errno == ENOTDIR), "no-follow ancestor open rejects link");
}
static void final_snapshot(void) {
    printf(",\"finalSnapshot\":{"); first_observation = 1;
    observe("generation", "", 0); observe("dataRoot", "data", 0); observe("receipt", "receipt.json", 0);
    observe("regular", "data/regular.bin", 0); observe("directory", "data/entries", 0);
    observe("symlink", "data/symbolic", 0); observe("ancestor", "data/ancestor", 0);
    observe("ancestorLeaf", "data/ancestor/regular.bin", 0); printf("}");
}
int main(int argc, char **argv) {
    alarm(20);
    need(argc == 4 && (!strcmp(argv[1], "mutate") || !strcmp(argv[1], "verify")), "usage: fixture mutate|verify PRIMARY ALIAS");
    primary = argv[2]; alias = argv[3]; need(primary[0] == '/' && alias[0] == '/' && strlen(primary) < 2048 && strlen(alias) < 2048, "absolute bounded aliases");
    printf("{\"formatVersion\":1,\"scope\":\"linux-glibc-stat-alias-mutation-fixture\",\"mode\":\"%s\",\"observations\":{", argv[1]);
    first_observation = 1; if (!strcmp(argv[1], "mutate")) mutation(); printf("}");
    final_snapshot(); printf(",\"metadataVisibleMutationsOnly\":true,\"unchangedMetadataCorruptionDetectionClaimed\":false}\n");
    need(fflush(stdout) == 0, "stat report flush"); return 0;
}
