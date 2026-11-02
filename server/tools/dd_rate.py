import subprocess, time, lucy_live, lucy_stream
cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST, "sh -s"]
for depth, count in ((1, 4), (2, 4), (4, 4), (2, 1)):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    p.stdin.write(lucy_stream.REMOTE_SERVER.encode())
    n = 0; out = 0; t0 = time.time()
    while time.time() - t0 < 6:
        while out < depth:
            p.stdin.write(f"1 {count}\n".encode()); out += 1
        want = count * 4096; got = 0
        while got < want:
            got += len(p.stdout.read(want - got))
        out -= 1; n += 1
    print(f"depth {depth} blocks {count}: {n/6:.1f} req/s", flush=True)
    p.kill()
