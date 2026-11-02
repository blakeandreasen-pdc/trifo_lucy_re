#define _GNU_SOURCE
/* depthdump: stream Lucy's ToF frames and some raw RGB stills to stdout for the 3D scanner.
 *   depthdump <seconds> <rgb_every_s> <points_every_n>
 * Records, each starting "<tag:1> <u64 ts_us> <u32 len>" then len bytes:
 *   D  45 bytes raw pose5d item (09 x 11 y 19 yaw 21 roll 29 pitch; zeros if absent), then
 *      z as u16 in 0.1 mm, confidence u8 (x255), amplitude u8; 224x172 each
 *   P  full point cloud, 224x172 x (x,y,z) float32 metres, every Nth frame (for the pixel rays)
 *   R  NV12 1920x1080
 * Frames changed during the copy are dropped; if the link is slow, frames are skipped rather than
 * queued. Read-only: it only maps the SHM rings.
 * Build (WSL): aarch64-linux-gnu-gcc -static -O2 -o depthdump depthdump.c */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define W 224
#define H 172
#define NPTS (W * H)
#define D_SLOT 0x100000
#define R_SLOT 0x400000
#define RGB_BYTES (1920 * 1080 * 3 / 2)

static const unsigned char M_PTS[8] = {0x08, 0x80, 0x9c, 0x1c, 0x12, 0x80, 0x9c, 0x1c};
static const unsigned char M_CONF[8] = {0x08, 0x80, 0xb4, 0x09, 0x12, 0x80, 0xb4, 0x09};
static const unsigned char M_IMG[10] = {0x08, 0xac, 0x01, 0x10, 0xe0, 0x01, 0x22, 0x80, 0xad, 0x02};
static const unsigned char M_POSE[3] = {0x2a, 0x2d, 0x09};

static const unsigned char *map(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); exit(1); }
    struct stat st;
    fstat(fd, &st);
    const unsigned char *m = mmap(NULL, st.st_size, PROT_READ, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) { perror("mmap"); exit(1); }
    return m;
}

/* newest slot: returns its timestamp, sets *msg, *len and *mo_out (meta offset) */
static unsigned long long newest(const unsigned char *m, size_t stride, const unsigned char **msg, unsigned long long *len, size_t *mo_out) {
    unsigned long long best = 0;
    for (int k = 0; k < 3; k++) {
        size_t mo = 0x1000 + k * stride + 0x8c + 0x20 * k;
        unsigned long long one, ts, ln;
        memcpy(&one, m + mo, 8); memcpy(&ts, m + mo + 8, 8); memcpy(&ln, m + mo + 16, 8);
        if (one == 1 && ts > best && ln > 0 && ln < stride) { best = ts; *msg = m + mo + 24; *len = ln; *mo_out = mo; }
    }
    return best;
}

static void rec(char tag, unsigned long long ts, unsigned len, const void *a) {
    fwrite(&tag, 1, 1, stdout); fwrite(&ts, 8, 1, stdout); fwrite(&len, 4, 1, stdout);
    fwrite(a, 1, len, stdout);
    fflush(stdout);
}

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

int main(int argc, char **argv) {
    double secs = argc > 1 ? atof(argv[1]) : 60, rgb_every = argc > 2 ? atof(argv[2]) : 3;
    int pts_every = argc > 3 ? atoi(argv[3]) : 25;
    const unsigned char *dm = map("/dev/shm/TrifoSemaphore_lucy_camera-depth_data");
    const unsigned char *rm = map("/dev/shm/TrifoSemaphore_lucy_camera-image_data");
    static float pts[NPTS * 3], conf[NPTS];
    static unsigned char img[NPTS], pose[45], out[45 + NPTS * 4];
    unsigned char *rgb = malloc(RGB_BYTES);
    unsigned long long last = 0, n = 0, last_r = 0;
    double t0 = now(), next_rgb = t0;
    while (now() - t0 < secs) {
        const unsigned char *msg = NULL; unsigned long long ln = 0; size_t mo = 0;
        unsigned long long ts = newest(dm, D_SLOT, &msg, &ln, &mo);
        if (ts && ts != last) {
            const unsigned char *p = memmem(msg, ln, M_PTS, 8), *c = memmem(msg, ln, M_CONF, 8), *a = memmem(msg, ln, M_IMG, 10), *q = memmem(msg, ln, M_POSE, 3);
            if (p && c && a) {
                memcpy(pts, p + 8, sizeof pts); memcpy(conf, c + 8, sizeof conf); memcpy(img, a + 10, sizeof img);
                memset(pose, 0, 45);
                if (q && (size_t)(q - msg) + 47 <= ln) memcpy(pose, q + 2, 45);
                unsigned long long ts2; memcpy(&ts2, dm + mo + 8, 8);
                if (ts2 == ts) {
                    unsigned short *z = (unsigned short *)(out + 45);
                    unsigned char *cu = out + 45 + NPTS * 2, *au = cu + NPTS;
                    for (int i = 0; i < NPTS; i++) {
                        float v = pts[3 * i + 2] * 10000.f;
                        z[i] = v > 0 && v < 65535 ? (unsigned short)v : 0;
                        float f = conf[i] * 255.f;
                        cu[i] = f > 0 ? (f > 255 ? 255 : (unsigned char)f) : 0;
                        au[i] = img[i];
                    }
                    memcpy(out, pose, 45);
                    rec('D', ts, sizeof out, out);
                    if (n % pts_every == 0) rec('P', ts, sizeof pts, pts);
                    n++;
                }
            }
            last = ts;
        }
        if (rgb_every > 0 && now() >= next_rgb) {
            unsigned long long rt = newest(rm, R_SLOT, &msg, &ln, &mo);
            if (rt && rt != last_r && ln >= RGB_BYTES) {
                memcpy(rgb, msg + ln - RGB_BYTES, RGB_BYTES);
                unsigned long long rt2; memcpy(&rt2, rm + mo + 8, 8);
                if (rt2 == rt) {
                    rec('R', rt, RGB_BYTES, rgb);
                    last_r = rt;
                    next_rgb = now() + rgb_every;
                }
            }
        }
        usleep(10000);
    }
    return 0;
}
