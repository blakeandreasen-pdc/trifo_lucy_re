# Lucy Local Control — Setup Guide (Windows, unrooted)

This folder lets you bring your Trifo Lucy vacuum back to life after the
official cloud servers went dark. You don't need to root or SSH into the
robot — you just point her at a server running on your PC instead.

**What you need**

- Lucy on your Wi-Fi (powered on, LEDs normal).
- A Windows PC on the **same Wi-Fi network** as Lucy.
- Python 3.8+ on that PC (<https://python.org> — tick "Add to PATH").
- Admin rights on the PC (needed once to open firewall ports).
- A way to override DNS on your network (see step 3).

---

## 1. Install the server

1. Copy this whole folder somewhere permanent, e.g.
   `C:\Lucy\lucy_server_portable\`. Don't leave it in Downloads.
2. Double-click **`install.bat`** and click *Yes* on the UAC prompt.
   That will:
   - install the `pyyaml` Python package if missing,
   - open Windows Firewall ports (443, 80, 7990, 17766, 8080, 9999),
   - create a scheduled task **LucyServer** that starts on every boot,
   - start the server immediately.

The server runs hidden in the background. Check it's alive by opening
<http://localhost:8080/> — you should see the dark-themed Lucy control
panel. It'll say "Server offline" for Lucy until DNS is redirected.

A log file `capture_log.txt` is written in the install folder. Open
it with Notepad to see what the server is doing.

---

## 2. Find your PC's LAN IP

Open PowerShell or Command Prompt and run:

```
ipconfig
```

Look for "IPv4 Address" under your Wi-Fi adapter, e.g. `192.168.1.42`.
Write it down — call it `<PC_IP>`.

> **Tip:** give the PC a static DHCP lease on the router so the IP
> doesn't drift. Otherwise Lucy will stop connecting the next time the
> PC gets a new address.

---

## 3. Redirect Lucy's DNS

Lucy always tries to reach two hostnames:

- `euiot.trifo.com`        (MQTT broker)
- `eudispatch.trifo.com`   (dispatch)

You need to make those resolve to `<PC_IP>` on your LAN. Pick **one**
method below.

### Method A — Router DNS override (easiest, recommended)

Most routers let you add "DNS overrides" or "local DNS records". The
location in the admin UI varies:

| Router / firmware          | Where to look |
| -------------------------- | ------------- |
| OpenWrt                    | Network → DHCP and DNS → *Addresses* (`/euiot.trifo.com/<PC_IP>`) |
| pfSense / OPNsense         | Services → DNS Resolver → Host Overrides |
| UniFi (UDM / Dream Router) | Settings → Networks → (LAN) → DHCP → DNS / or Profiles → DNS |
| Asus                       | WAN → DNS → "Manually Assigned IP in the DHCP scope" doesn't do it; use **AiProtection off → LAN → DHCP Server → DNS Entries** on newer firmware, or flash Merlin + dnsmasq add-on |
| TP-Link (Omada)            | Settings → Network Security → DNS Filtering / or DHCP custom DNS |
| Pi-hole                    | Local DNS → DNS Records (add both hostnames) |
| AdGuard Home               | Filters → DNS rewrites |
| eero, Google Nest Wi-Fi    | *Not supported* — use Method B |

Add **both** entries:

```
euiot.trifo.com       →  <PC_IP>
eudispatch.trifo.com  →  <PC_IP>
```

After saving, reboot Lucy by flicking the switch on her underside or
picking her up and putting her back on the dock for a minute. Within
~30 seconds of rebooting she should connect to your PC — the web UI
will switch from "offline" to showing her real status.

### Method B — Pi-hole / AdGuard Home on the network

If Method A isn't available, run Pi-hole or AdGuard Home on a spare
device (Raspberry Pi, another PC, NAS). Point your router's "DNS server
to hand out via DHCP" at it, then add the two records above as local
DNS entries inside Pi-hole/AdGuard. Same effect.

### Method C — Install a tiny DNS server on this same PC

If the router is locked down, the PC running the server can also be the
DNS server for Lucy:

1. Install **Acrylic DNS Proxy** (free, <https://mayakron.altervista.org/>).
2. In Acrylic's `AcrylicHosts.txt`, add:
   ```
   <PC_IP>  euiot.trifo.com
   <PC_IP>  eudispatch.trifo.com
   ```
3. Start the Acrylic service.
4. In your router's DHCP settings, set the PC's IP as the primary DNS
   server handed out to clients. Or, if the router won't let you,
   give Lucy a static DHCP lease with the PC as her DNS.

### Method D — Advanced: already-rooted Lucy

Only applies if Lucy is rooted (this folder assumes she isn't, but for
completeness):

```
ssh root@<lucy_ip>
echo "<PC_IP> euiot.trifo.com"       >> /data/local/tmp/hosts
echo "<PC_IP> eudispatch.trifo.com"  >> /data/local/tmp/hosts
mount --bind /data/local/tmp/hosts /etc/hosts
kill $(pidof cloud_node)
```

---

## 4. Confirm Lucy is connected

1. Open <http://localhost:8080/>.
2. Power-cycle Lucy (or pick her off the dock and set her back).
3. Within a minute, the status dot should go green.
4. `capture_log.txt` will show `*** Lucy is now ONLINE` and her serial
   number and MAC address.
5. `state.yaml` will auto-populate with Lucy's serial, MAC and subid.
   Back that file up — it's the only Lucy-specific bit of state.

Try the control buttons: **Locate** is the safest test (she'll just
beep/speak). **Dock** is the next safest. **Start** sends her out
cleaning.

From PowerShell you can also run:

```
py lucy_control.py locate
py lucy_control.py dock
py lucy_control.py status
```

---

## 5. Schedule cleaning runs

The web UI has a "Schedule" card — add time + command entries there
and they'll persist in `schedule.json`.

Or edit `config.yaml`:

```yaml
schedule:
  - time: "09:00"
    command: start
    days: [mon, tue, wed, thu, fri]
  - time: "10:30"
    command: dock
    days: [mon, tue, wed, thu, fri]
```

**Note:** schedules only fire while the server is running. Since
`install.bat` configures the server to start on every boot, that's
fine as long as the PC is on at the scheduled time. If the PC is
asleep, the schedule slot is skipped (Windows won't wake it for us).

To make the PC wake for schedule events, open Task Scheduler (Win+R →
`taskschd.msc`), find **LucyServer** under Task Scheduler Library,
right-click → Properties → Conditions → tick "Wake the computer to
run this task". Or set Power Options to "Never sleep" for this PC.

---

## Troubleshooting

**Lucy's status stays "offline" in the web UI**

- On the PC: `nslookup euiot.trifo.com` from Lucy's network should
  return `<PC_IP>`. If it returns the real Trifo IP, your DNS override
  isn't being hit. Usually means the router is still handing out its
  upstream DNS, not the local override. Check the router's DHCP DNS
  settings.
- Check Windows Firewall didn't quietly block inbound TCP on 443 /
  7990 / 17766. Re-run `install.bat` to re-add the rule.
- Power-cycle Lucy after changing DNS. She caches DNS for a while.

**"Port 443 already in use" in the log**

- Something else is listening on 443 (IIS, Skype, VPN client, Docker
  Desktop). Stop that service, or set `https_port: null` in
  `config.yaml` (voice/language-pack requests will fail silently,
  which is harmless — Lucy will just be less talky).

**`install.bat` asks for admin every time**

- That's expected. Windows requires elevation to open firewall ports
  and create SYSTEM scheduled tasks. You only need to run it once.

**I want to watch the server live, not as a background task**

- Run `uninstall.bat` to remove the background task, then
  double-click `start_server.bat`. It opens a console window you can
  watch.

---

## Files

| File                    | Purpose |
| ----------------------- | ------- |
| `capture_server.py`     | The server itself — handles all Trifo protocol emulation |
| `config.yaml`           | Ports, IP, scheduling, logging options |
| `state.yaml`            | Auto-populated device state (don't edit unless Lucy's hardware changed) |
| `schedule.json`         | Editable schedule (created by the web UI) |
| `mqtt_cert.pem` / `mqtt_key.pem` | Self-signed TLS cert Lucy accepts |
| `lucy_control.py`       | Command-line tool: `py lucy_control.py dock` |
| `send_command.py`       | Low-level: `py send_command.py raw 2 start` |
| `web/index.html`        | The web UI |
| `start_server.bat`      | Manual launcher (visible console) |
| `install.bat`           | Configures auto-start + firewall |
| `uninstall.bat`         | Removes auto-start + firewall rule |
| `capture_log.txt`       | Runtime log (auto-created) |

---

## Moving to a different PC later

1. Copy the whole folder over.
2. Run `install.bat` on the new PC.
3. Update the router DNS entries to point at the new PC's IP.
4. Keep `state.yaml` from the old install so Lucy's auth token and
   subid carry over — otherwise she'll re-register, which is fine too.
