#define _GNU_SOURCE
/* depthscan: Lucy's ToF point cloud -> obstacle points in her own frame, a few times a second.
 *   depthscan <a> <b> <c> <cam_fwd> <h_min> <h_max> [hz]
 * Reads the newest frame of /dev/shm/TrifoSemaphore_lucy_camera-depth_data (3-slot ring: slots of
 * 1 MiB from 0x1000; slot k's meta u64 1 | u64 ts_us | u64 len at slot + 0x8c + 0x20*k, then the
 * protobuf). The point cloud is the blob after the bytes 08 80 9c 1c 12 80 9c 1c: 224x172 points of
 * (x right, y down, z forward) float32 metres in the camera frame.
 * Floor plane (fitted once, depth_calib.json): y = a*x + b*z + c. A point counts as an obstacle if
 * its height above that plane is between h_min and h_max (she's ~10 cm tall: higher things she can
 * pass under). Output per new frame, one line:
 *   S <ts_us> <n> <fwd_cm>,<left_cm> ...    (2 cm cells with >= 2 points; her centre = 0,0)
 * cam_fwd = camera distance in front of her centre (m). If the frame changes while we copy it, it is
 * dropped (no torn frames).
 * Build (WSL): aarch64-linux-gnu-gcc -static -O2 -o depthscan depthscan.c -lm */
#include <fcntl.h>
#include <math.h>
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
#define SHM "/dev/shm/TrifoSemaphore_lucy_camera-depth_data"
#define GRID 200 /* 2 cm cells, -2..2 m */

static const unsigned char MAGIC[8] = {0x08, 0x80, 0x9c, 0x1c, 0x12, 0x80, 0x9c, 0x1c};

static void slot_meta(const unsigned char *m, int k, unsigned long long *ts, unsigned long long *len, size_t *off) {
    size_t mo = 0x1000 + (size_t)k * 0x100000 + 0x8c + 0x20 * k;
    unsigned long long one;
    memcpy(&one, m + mo, 8);
    memcpy(ts, m + mo + 8, 8);
    memcpy(len, m + mo + 16, 8);
    *off = mo + 24;
    if (one != 1) *ts = 0;
}

int main(int argc, char **argv) {
    if (argc < 7) {
        fprintf(stderr, "usage: depthscan a b c cam_fwd h_min h_max [hz]\n");
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    double a = atof(argv[1]), b = atof(argv[2]), c = atof(argv[3]), fwd0 = atof(argv[4]);
    double hmin = atof(argv[5]), hmax = atof(argv[6]), hz = argc > 7 ? atof(argv[7]) : 5;
    double n = sqrt(1 + a * a + b * b);
    /* floor-aligned axes in the camera frame: forward u = (0,b,1)/|.|, right r = (1,a,0)/|.| */
    double un = sqrt(1 + b * b), rn = sqrt(1 + a * a);
    int fd = open(SHM, O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }
    struct stat st;
    fstat(fd, &st);
    const unsigned char *m = mmap(NULL, st.st_size, PROT_READ, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) { perror("mmap"); return 1; }
    float *pts = malloc(NPTS * 12);
    static unsigned short cnt[GRID][GRID];
    unsigned long long last = 0;
    for (;;) {
        int best = -1;
        unsigned long long bts = 0, blen = 0;
        size_t boff = 0;
        for (int k = 0; k < 3; k++) {
            unsigned long long ts, len;
            size_t off;
            slot_meta(m, k, &ts, &len, &off);
            if (ts > bts && len > 0 && len < 0x100000) { bts = ts; blen = len; boff = off; best = k; }
        }
        if (best < 0 || bts == last) { usleep(20000); continue; }
        const unsigned char *msg = m + boff;
        const unsigned char *p = memmem(msg, blen, MAGIC, 8);
        if (!p || (size_t)(p - msg) + 8 + NPTS * 12 > blen) { last = bts; continue; }
        memcpy(pts, p + 8, NPTS * 12);
        unsigned long long ts2, len2;
        size_t off2;
        slot_meta(m, best, &ts2, &len2, &off2);
        if (ts2 != bts) continue; /* overwritten while copying: try again */
        last = bts;
        memset(cnt, 0, sizeof cnt);
        for (int i = 0; i < NPTS; i++) {
            float x = pts[3 * i], y = pts[3 * i + 1], z = pts[3 * i + 2];
            if (!(z > 0.05f) || !isfinite(x) || !isfinite(y)) continue;
            double h = (c + a * x + b * z - y) / n;
            double f = (b * y + z) / un + fwd0, l = -(x + a * y) / rn;
            /* she pitches a little as she drives and the floor is lumpy: far away that lifts the
               floor by a few cm, so the cut-off rises with distance (+2.5 cm per metre) */
            if (h < hmin + 0.025 * (f - fwd0) || h > hmax) continue;
            int gi = (int)floor(f / 0.02) + GRID / 2, gj = (int)floor(l / 0.02) + GRID / 2;
            if (gi < 0 || gi >= GRID || gj < 0 || gj >= GRID) continue;
            if (cnt[gi][gj] < 65535) cnt[gi][gj]++;
        }
        int total = 0;
        static char line[200000];
        size_t k = 0;
        for (int gi = 0; gi < GRID; gi++)
            for (int gj = 0; gj < GRID; gj++)
                if (cnt[gi][gj] >= 2 && k < sizeof line - 32) {
                    k += sprintf(line + k, " %d,%d", (gi - GRID / 2) * 2 + 1, (gj - GRID / 2) * 2 + 1);
                    total++;
                }
        line[k] = 0;
        printf("S %llu %d%s\n", bts, total, line);
        usleep((useconds_t)(1e6 / hz));
    }
}
