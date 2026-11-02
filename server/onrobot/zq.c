/* zq: minimal ZeroMQ (ZMTP 3.0, NULL mechanism) client for Lucy's TrifoIPC unix sockets.
 *   zq <socket path> <our socket type, e.g. DEALER|PAIR|PUSH|REQ> [hex message|@id:payloadhex|-] [listen_ms]
 *   zq <socket path> DEALER -s      stream mode: one connection, then send one "@id:payloadhex" per
 *                                   stdin line until EOF (her nodes are slow to pick up new
 *                                   connections - ~1-2 s - so live driving keeps one open)
 * "@id:payloadhex" wraps a ServiceMsg in RPCRequestBase {1 id, 4 priority 100, 7 timestamp,
 * 8 payload} with timestamp = CLOCK_BOOTTIME in microseconds - the clock her own nodes use.
 * (Never send other timestamps: sensor_node refuses any OVERWRITE request older than the newest
 * it has seen, so a future timestamp locks guidance out until she restarts.)
 * Does the greeting + READY handshake (prints the peer's READY properties), sends the message
 * as one frame, then prints every frame received (hex) for listen_ms (default 1500).
 * Build (WSL): aarch64-linux-gnu-gcc -static -O2 -o zq zq.c */
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static int fd;

static long now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000L + t.tv_nsec / 1000000L;
}

static int read_n(unsigned char *b, size_t n, long deadline) {
    size_t got = 0;
    while (got < n) {
        long left = deadline - now_ms();
        if (left <= 0) return -1;
        struct pollfd p = {fd, POLLIN, 0};
        if (poll(&p, 1, (int)left) <= 0) continue;
        ssize_t r = read(fd, b + got, n - got);
        if (r <= 0) return -2;
        got += r;
    }
    return 0;
}

/* one ZMTP frame: returns flags, fills body (malloc'd) and len */
static int read_frame(unsigned char **body, size_t *len, long deadline) {
    unsigned char h[9];
    int r = read_n(h, 1, deadline);
    if (r) return r;
    size_t n;
    if (h[0] & 0x02) {
        if ((r = read_n(h + 1, 8, deadline))) return r;
        n = 0;
        for (int i = 1; i < 9; i++) n = (n << 8) | h[i];
    } else {
        if ((r = read_n(h + 1, 1, deadline))) return r;
        n = h[1];
    }
    *body = malloc(n + 1);
    if ((r = read_n(*body, n, deadline))) return r;
    *len = n;
    return h[0];
}

static void send_frame(int flags, const unsigned char *b, size_t n) {
    unsigned char h[9];
    size_t hl;
    if (n > 255) {
        h[0] = flags | 0x02;
        for (int i = 0; i < 8; i++) h[1 + i] = (unsigned char)(n >> (56 - 8 * i));
        hl = 9;
    } else {
        h[0] = flags;
        h[1] = (unsigned char)n;
        hl = 2;
    }
    write(fd, h, hl);
    if (n) write(fd, b, n);
}

static void send_rpc(const char *arg) {
    int rq = arg[1] == '@'; /* "@@id:payloadhex" adds field 3 = 1, as manager_node's clients do */
    unsigned long id = strtoul(arg + 1 + rq, NULL, 10);
    const char *ph = strchr(arg, ':');
    if (!ph) return;
    ph++;
    size_t pl = strlen(ph) / 2;
    unsigned char *msg = malloc(pl + 64);
    size_t k2 = 0;
    struct timespec ts;
    clock_gettime(CLOCK_BOOTTIME, &ts);
    unsigned long long us = (unsigned long long)ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000;
    msg[k2++] = 0x08;
    for (unsigned long v = id; ; v >>= 7) { if (v < 0x80) { msg[k2++] = (unsigned char)v; break; } msg[k2++] = (unsigned char)(v | 0x80); }
    if (rq) { msg[k2++] = 0x18; msg[k2++] = 1; }
    msg[k2++] = 0x20; msg[k2++] = 100;
    msg[k2++] = 0x38;
    for (unsigned long long v = us; ; v >>= 7) { if (v < 0x80) { msg[k2++] = (unsigned char)v; break; } msg[k2++] = (unsigned char)(v | 0x80); }
    msg[k2++] = 0x42;
    for (size_t v = pl; ; v >>= 7) { if (v < 0x80) { msg[k2++] = (unsigned char)v; break; } msg[k2++] = (unsigned char)(v | 0x80); }
    for (size_t i = 0; i < pl; i++) sscanf(ph + 2 * i, "%2hhx", &msg[k2++]);
    send_frame(0x00, msg, k2);
    printf("sent rpc id %lu ts %llu (%zu bytes)\n", id, us, k2);
    fflush(stdout);
    free(msg);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: zq <path> <type> [hex|-] [listen_ms]\n");
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    long listen_ms = argc > 4 ? atol(argv[4]) : 1500;
    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    strncpy(a.sun_path, argv[1], sizeof a.sun_path - 1);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) < 0) {
        printf("connect failed: %s\n", strerror(errno));
        return 1;
    }
    /* greeting: signature, version 3.0, mechanism NULL, as-server 0, filler */
    unsigned char g[64];
    memset(g, 0, sizeof g);
    g[0] = 0xff;
    g[9] = 0x7f;
    g[10] = 3;
    g[11] = 0;
    memcpy(g + 12, "NULL", 4);
    write(fd, g, 64);
    long dl = now_ms() + 3000;
    unsigned char pg[64];
    if (read_n(pg, 64, dl)) {
        printf("no greeting\n");
        return 1;
    }
    printf("peer greeting: version %d.%d mechanism %.20s\n", pg[10], pg[11], pg + 12);
    /* our READY */
    unsigned char rd[64];
    size_t k = 0;
    const char *t = argv[2];
    rd[k++] = 5;
    memcpy(rd + k, "READY", 5);
    k += 5;
    rd[k++] = 11;
    memcpy(rd + k, "Socket-Type", 11);
    k += 11;
    size_t tl = strlen(t);
    rd[k++] = 0; rd[k++] = 0; rd[k++] = 0; rd[k++] = (unsigned char)tl;
    memcpy(rd + k, t, tl);
    k += tl;
    send_frame(0x04, rd, k);
    /* peer READY (or ERROR) */
    unsigned char *b;
    size_t n;
    int f = read_frame(&b, &n, dl);
    if (f < 0) {
        printf("no READY (%d)\n", f);
        return 1;
    }
    printf("peer command: ");
    for (size_t i = 0; i < n; i++) putchar(b[i] >= 32 && b[i] < 127 ? b[i] : '.');
    printf("\n");
    if (strcmp(argv[2], "SUB") == 0) {
        /* ZMTP 3.0 subscription: a message whose first byte is 1, then the prefix (empty = all) */
        unsigned char sub = 1;
        send_frame(0x00, &sub, 1);
    }
    if (argc > 3 && strcmp(argv[3], "-s") == 0) {
        char line[4096];
        while (fgets(line, sizeof line, stdin)) {
            line[strcspn(line, "\r\n")] = 0;
            if (line[0] == '@') send_rpc(line);
            /* drain anything the peer sent so its buffer never fills */
            struct pollfd p = {fd, POLLIN, 0};
            while (poll(&p, 1, 0) > 0 && (p.revents & POLLIN)) {
                unsigned char tmp[4096];
                if (read(fd, tmp, sizeof tmp) <= 0) { printf("closed\n"); return 1; }
            }
        }
        return 0;
    }
    if (argc > 3 && argv[3][0] == '@') {
        send_rpc(argv[3]);
    } else if (argc > 3 && strcmp(argv[3], "-") != 0) {
        size_t m = strlen(argv[3]) / 2;
        unsigned char *buf = malloc(m);
        for (size_t i = 0; i < m; i++) sscanf(argv[3] + 2 * i, "%2hhx", &buf[i]);
        send_frame(0x00, buf, m);
        printf("sent %zu\n", m);
    }
    long end = now_ms() + listen_ms;
    while (1) {
        f = read_frame(&b, &n, end);
        if (f == -1) break;
        if (f < 0) {
            printf("closed\n");
            break;
        }
        printf("frame t%ld flags %d len %zu: ", now_ms() % 1000000, f, n);
        for (size_t i = 0; i < n; i++) printf("%02x", b[i]);
        printf("\n");
        fflush(stdout);
        free(b);
    }
    close(fd);
    return 0;
}
