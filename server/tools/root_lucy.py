#!/usr/bin/env python3
"""
root_lucy.py - automate the timing-critical parts of rooting a Trifo Lucy.

The soldering (UART to TX/RX/GND) still has to be done by hand, but the three
stressful bits that used to need exact human timing are automated here:

  1. Catch the U-Boot prompt  - spams Ctrl+C on the serial line and watches
     for the "=>" prompt, so you don't have to hammer the keyboard at the
     right millisecond.
  2. Trigger the alternate boot mode - sends `ext4ls mmc 0:e` the instant the
     prompt appears. That alt mode is what makes ADB actually usable (a normal
     boot shows an ADB device but every connection fails).
  3. Win the ADB window - `adb wait-for-device` grabs the short window the
     moment she enumerates, pushes the Dropbear host key + your public key to
     /data/.ssh/, verifies, and keeps retrying if the window bounces.

Full background: "Lucy Dump/rooting/Getting_root_on_lucy.md".

Usage (on the laptop physically wired to the Lucy, with adb installed):

    python root_lucy.py --port COM5 --key C:\\path\\to\\trifo_lucy.pub

Then power Lucy on (or power-cycle) when it tells you to.

Dry run first, without a Lucy attached, to sanity-check paths/adb:

    python root_lucy.py --port COM5 --key trifo_lucy.pub --check

Skip the iron and test the unconfirmed Power+Home button combo instead of
UART (just polls for a usable ADB device while you hold the combo):

    python root_lucy.py --key trifo_lucy.pub --buttons
"""
import argparse
import os
import subprocess
import sys
import threading
import time

ADB_VID = "0x2207"          # Rockchip, for legacy adb_usb.ini
UBOOT_DEFAULT_PROMPT = "=>"
ALT_MODE_CMD = b"ext4ls mmc 0:e\r\n"
SSH_DIR = "/data/.ssh"
HOST_KEY = SSH_DIR + "/dropbear_rsa_host_key"
AUTH_KEYS = SSH_DIR + "/authorized_keys"


def log(msg):
    print(msg, flush=True)


def banner(msg):
    log("\n" + "=" * 60 + "\n" + msg + "\n" + "=" * 60)


# ---------------------------------------------------------------- preflight

def read_pubkey(path):
    if not os.path.isfile(path):
        sys.exit(f"[!] Public key not found: {path}")
    data = open(path, "r", encoding="utf-8", errors="replace").read().strip()
    if not data.startswith("ssh-rsa"):
        sys.exit("[!] Public key must start with 'ssh-rsa' (Dropbear 0.52 "
                 "needs an RSA key). Regenerate:\n"
                 "    ssh-keygen -t rsa -b 2048 -f trifo_lucy")
    return path


def ensure_adb_usb_ini():
    """Older adb needs the Rockchip VID whitelisted; harmless on newer adb."""
    d = os.path.join(os.path.expanduser("~"), ".android")
    f = os.path.join(d, "adb_usb.ini")
    try:
        os.makedirs(d, exist_ok=True)
        existing = open(f).read() if os.path.isfile(f) else ""
        if ADB_VID not in existing:
            with open(f, "a") as fh:
                fh.write(("" if existing.endswith("\n") or not existing else "\n")
                         + ADB_VID + "\n")
            log(f"[*] Added {ADB_VID} to {f}")
    except OSError as e:
        log(f"[!] Could not write adb_usb.ini ({e}); continuing anyway")


def adb(args, adb_bin, timeout=20, quiet=False):
    """Run an adb command, return (rc, combined_output)."""
    try:
        p = subprocess.run([adb_bin] + args, capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        if not quiet:
            for line in out.splitlines():
                log("    adb> " + line)
        return p.returncode, out
    except FileNotFoundError:
        sys.exit(f"[!] adb not found ('{adb_bin}'). Install it:\n"
                 "    winget install Google.PlatformTools\n"
                 "or pass --adb with the full path to adb.exe")
    except subprocess.TimeoutExpired:
        return 124, "(adb timed out)"


def check_adb(adb_bin):
    rc, out = adb(["version"], adb_bin, quiet=True)
    if rc != 0:
        sys.exit("[!] adb present but 'adb version' failed:\n" + out)
    log("[*] " + out.splitlines()[0].strip())


# ------------------------------------------------------------- key push (C)

def push_keys(adb_bin, pubkey):
    """One attempt at the key push. Returns True once authorized_keys is in place."""
    adb(["wait-for-device"], adb_bin, timeout=8, quiet=True)
    adb(["shell", "mkdir", "-p", SSH_DIR], adb_bin, timeout=8)
    # dropbearkey says "File exists" on a retry - that's fine.
    adb(["shell", "/system/bin/dropbearkey", "-t", "rsa", "-f", HOST_KEY],
        adb_bin, timeout=15)
    adb(["push", pubkey, AUTH_KEYS], adb_bin, timeout=15)
    rc, out = adb(["shell", "ls", "-la", SSH_DIR], adb_bin, timeout=8)
    return "authorized_keys" in out and "dropbear_rsa_host_key" in out


def adb_race(adb_bin, pubkey, window_s):
    banner("STAGE C: catching the ADB window and pushing keys")
    log("[*] Waiting for Lucy to appear as an ADB device...")
    deadline = time.time() + window_s
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        log(f"[*] push attempt {attempt}...")
        try:
            if push_keys(adb_bin, pubkey):
                return True
        except Exception as e:  # keep hammering; the window is short and flaky
            log(f"    (attempt error: {e})")
        time.sleep(1.0)
    return False


# -------------------------------------------------------- serial stages A/B

def serial_root(args, pubkey):
    import serial  # imported here so --buttons works without pyserial

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
    except Exception as e:
        sys.exit(f"[!] Could not open serial port {args.port} @ {args.baud}: {e}")

    banner("STAGE A: catching the U-Boot prompt")
    log(f"[*] Port {args.port} @ {args.baud} 8N1 open.")
    log("[*] Spamming Ctrl+C. >>> POWER LUCY ON (or power-cycle) NOW. <<<")
    log(f"[*] Watching for the U-Boot prompt '{args.prompt}' "
        f"(giving up after {args.uboot_timeout}s).")

    buf = ""
    deadline = time.time() + args.uboot_timeout
    got_prompt = False
    while time.time() < deadline:
        ser.write(b"\x03")                      # Ctrl+C
        chunk = ser.read(256)
        if chunk:
            text = chunk.decode("utf-8", "replace")
            sys.stdout.write(text)
            sys.stdout.flush()
            buf = (buf + text)[-400:]
            if args.prompt in buf:
                got_prompt = True
                break
        time.sleep(0.015)

    if not got_prompt:
        ser.close()
        sys.exit("\n[!] Never saw the U-Boot prompt. Check the UART wiring "
                 "(TX<->RX swapped?), baud (1500000), and that Ctrl+C is "
                 "interrupting the boot. Try again.")

    log(f"\n[*] Got the U-Boot prompt.")
    time.sleep(0.3)

    banner("STAGE B: triggering the alternate boot mode")
    ser.reset_input_buffer()
    ser.write(ALT_MODE_CMD)
    log(f"[*] Sent: {ALT_MODE_CMD.decode().strip()}")
    log("[*] Lucy is booting into alt mode (watch for a yellow LED). "
        "Boot log follows:")

    # Keep echoing the UART in the background while we race for ADB.
    stop = threading.Event()

    def echo():
        while not stop.is_set():
            chunk = ser.read(256)
            if chunk:
                sys.stdout.write(chunk.decode("utf-8", "replace"))
                sys.stdout.flush()

    t = threading.Thread(target=echo, daemon=True)
    t.start()

    ok = adb_race(args.adb, pubkey, args.adb_timeout)
    stop.set()
    t.join(timeout=1)
    ser.close()
    return ok


# ------------------------------------------------------------- buttons mode

def buttons_mode(args, pubkey):
    banner("BUTTON-COMBO TEST (no UART) - UNCONFIRMED")
    log("[*] This tries the unverified Power+Home route: if a button combo "
        "drops Lucy into the same alt/recovery mode, we skip the iron.")
    log("[*] Hold the combo per the guide and watch for the yellow LED.")
    log(f"[*] Polling for a usable ADB device for {args.adb_timeout}s...")
    return adb_race(args.adb, pubkey, args.adb_timeout)


# -------------------------------------------------------------------- main

def success_message(pubkey):
    key_priv = os.path.splitext(pubkey)[0]
    banner("DONE - keys are on Lucy")
    log("Now:")
    log("  1. Power-cycle Lucy and let it boot NORMALLY (do NOT interrupt U-Boot).")
    log("  2. Wait for it to join WiFi, find its IP (router DHCP table).")
    log("  3. SSH in:\n")
    log("     ssh -oKexAlgorithms=+diffie-hellman-group1-sha1 \\")
    log("         -oHostKeyAlgorithms=+ssh-rsa \\")
    log("         -oMACs=+hmac-sha1 \\")
    log("         -oPubkeyAcceptedAlgorithms=+ssh-rsa \\")
    log("         -o StrictHostKeyChecking=no \\")
    log(f"         -i {key_priv} \\")
    log("         root@<LUCY_IP>\n")
    log("  Expect a root shell:  uid=0(root) ...")


def main():
    ap = argparse.ArgumentParser(description="Automate rooting a Trifo Lucy.")
    ap.add_argument("--key", required=True,
                    help="path to your SSH public key (.pub, must be ssh-rsa)")
    ap.add_argument("--port", help="serial port for UART (e.g. COM5, /dev/ttyUSB0)")
    ap.add_argument("--baud", type=int, default=1500000)
    ap.add_argument("--prompt", default=UBOOT_DEFAULT_PROMPT,
                    help="U-Boot prompt string to detect (default '=>')")
    ap.add_argument("--adb", default="adb", help="path to adb binary")
    ap.add_argument("--uboot-timeout", type=int, default=90,
                    help="seconds to spam Ctrl+C waiting for U-Boot")
    ap.add_argument("--adb-timeout", type=int, default=120,
                    help="seconds to keep retrying the ADB key push")
    ap.add_argument("--buttons", action="store_true",
                    help="skip UART; test the Power+Home combo route instead")
    ap.add_argument("--check", action="store_true",
                    help="preflight only: validate key + adb, then exit")
    args = ap.parse_args()

    pubkey = read_pubkey(args.key)
    log(f"[*] Public key OK: {pubkey}")
    check_adb(args.adb)
    ensure_adb_usb_ini()
    adb(["kill-server"], args.adb, quiet=True)
    adb(["start-server"], args.adb, quiet=True)

    if args.check:
        log("[*] Preflight OK. Re-run without --check to do the real thing.")
        return

    if args.buttons:
        ok = buttons_mode(args, pubkey)
    else:
        if not args.port:
            sys.exit("[!] --port is required for the UART flow "
                     "(or use --buttons to try the no-solder route).")
        ok = serial_root(args, pubkey)

    if ok:
        success_message(pubkey)
    else:
        banner("NOT DONE")
        log("[!] Didn't confirm the keys landed. Nothing is broken - just "
            "power-cycle and try again. If the ADB device never showed, the "
            "alt-mode trigger didn't take.")
        sys.exit(1)


if __name__ == "__main__":
    main()
