/* usock: talk to one of Lucy's TrifoIPC unix sockets.
 *   usock <socket path> <hex bytes to send|-> [listen_ms]
 * Connects, sends the bytes (hex string, "-" = send nothing), then prints everything received
 * (as hex, one line per read) for listen_ms milliseconds (default 1500).
 * Build (WSL): aarch64-linux-gnu-gcc -static -O2 -o usock usock.c */
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static long now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000L + t.tv_nsec / 1000000L;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: usock <path> <hex|-> [listen_ms]\n");
        return 2;
    }
    long listen_ms = argc > 3 ? atol(argv[3]) : 1500;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    strncpy(a.sun_path, argv[1], sizeof a.sun_path - 1);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) < 0) {
        printf("connect failed: %s\n", strerror(errno));
        return 1;
    }
    printf("connected\n");
    if (strcmp(argv[2], "-") != 0) {
        size_t n = strlen(argv[2]) / 2;
        unsigned char *buf = malloc(n);
        for (size_t i = 0; i < n; i++) sscanf(argv[2] + 2 * i, "%2hhx", &buf[i]);
        ssize_t w = write(fd, buf, n);
        printf("sent %zd/%zu\n", w, n);
    }
    long end = now_ms() + listen_ms;
    unsigned char rb[8192];
    while (now_ms() < end) {
        struct pollfd p = {fd, POLLIN, 0};
        if (poll(&p, 1, (int)(end - now_ms())) <= 0) continue;
        ssize_t r = read(fd, rb, sizeof rb);
        if (r <= 0) {
            printf("closed (%zd)\n", r);
            break;
        }
        printf("recv %ld ", now_ms() % 100000);
        for (ssize_t i = 0; i < r; i++) printf("%02x", rb[i]);
        printf("\n");
        fflush(stdout);
    }
    close(fd);
    return 0;
}
