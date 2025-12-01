#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>

int main() {
    if (setuid(0) != 0) {
        perror("setuid");
        return 1;
    }
    if (setgid(0) != 0) {
        perror("setgid");
        return 1;
    }

    char *argv[] = {"/usr/bin/wg", "show", "all", "dump", NULL};
    execv("/usr/bin/wg", argv);

    perror("execv");
    return 1;
}
