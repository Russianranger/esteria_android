/* Adapted from Russianranger/fta-launcher; see FTA-MIT-LICENSE.txt. */
/* Synthetic Linux process tree; no client files or Windows runtime. */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static int finish(pid_t child, int normal) {
    alarm(20);
    printf("ESTERIA_PROOT_FIXTURE_PID %ld\n", (long)getpid());
    fflush(stdout);
    if (!normal) for (;;) pause();
    if (child > 0) {
        int status;
        if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    int normal = argc == 2 && strcmp(argv[1], "--normal") == 0;
    pid_t child = fork();
    if (child < 0) return 2;
    if (child > 0) return finish(child, normal);
    if (setsid() < 0) return 3;
    pid_t grandchild = fork();
    if (grandchild < 0) return 4;
    if (grandchild == 0 && setsid() < 0) return 5;
    return finish(grandchild, normal);
}
