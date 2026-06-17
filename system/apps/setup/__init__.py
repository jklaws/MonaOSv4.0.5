import sys
import os

sys.path.insert(0, "/system/apps/setup")
sys.path.insert(0, "/")
os.chdir("/system/apps/setup")

import badgeware  # noqa: F401  (builtins: screen, color, shape, image, badge, run, BUTTON_*)
screen.antialias = X2
import time
import json
import network
import qrcode
import machine

Portal = __import__("/system/portal").Portal
fsutil = __import__("/system/fsutil")     # atomic, crash-safe writes
# NOTE: the frozen `wifi` store does `import secrets`, which raises if no
# secrets.py exists yet. Setup is the bootstrap that runs BEFORE credentials
# exist, so we import `wifi` lazily in on_save() (after we've written secrets) —
# never at module load, or opening Setup on a fresh/wiped device crashes.

SETTINGS = "/settings.json"
SECRETS = "/secrets.py"

big = pixel_font.load("/system/assets/fonts/absolute.ppf")
small = pixel_font.load("/system/assets/fonts/ark.ppf")
tiny = pixel_font.load("/system/assets/fonts/corpsavage.ppf")   # compact status/fallback line

BG = color.rgb(13, 17, 23)
PANEL = color.rgb(26, 31, 40)
WHITE = color.rgb(238, 244, 250)
MUTED = color.rgb(150, 162, 176)
LAV = color.rgb(170, 140, 248)
GREEN = color.rgb(63, 200, 110)
LIME = color.rgb(211, 250, 55)


def load_settings():
    return fsutil.read_json(SETTINGS, {})


def get_secret(key):
    try:
        with open(SECRETS) as f:
            for ln in f:
                if ln.strip().startswith(key):
                    return ln.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return ""


def set_secrets(updates):
    lines = fsutil.read_text(SECRETS).split("\n")
    if lines == [""]:
        lines = []
    for k, v in updates.items():
        newln = "%s = %r" % (k, v)
        done = False
        for i, ln in enumerate(lines):
            if ln.strip().startswith(k):
                lines[i] = newln
                done = True
                break
        if not done:
            lines.append(newln)
    try:
        fsutil.write_text(SECRETS, "\n".join(lines))   # atomic temp+rename
    except Exception as e:  # noqa: BLE001
        print("secrets write err", e)


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def scan_networks(sta):
    found = {}
    try:
        for n in sta.scan():                 # works even with the AP already up
            nm = "".join(ch for ch in n[0].decode("utf-8", "replace")
                         if 32 <= ord(ch) <= 126)
            if not nm.strip():
                continue
            if nm not in found or n[3] > found[nm]:
                found[nm] = n[3]
    except Exception as e:  # noqa: BLE001
        print("scan err", e)
    return sorted(found.keys(), key=lambda k: found[k], reverse=True)[:10]


def build_page(nets):
    html = open("/system/apps/setup/page.html").read()
    d = load_settings()
    opts = "".join("<option>%s</option>" % _esc(n) for n in nets)
    html = html.replace("{{NETWORKS}}", opts)
    html = html.replace("{{GITHUB}}", _esc(get_secret("GITHUB_USERNAME")))
    html = html.replace("{{LINKEDIN}}", _esc(d.get("linkedin_url", "")))
    soc = d.get("socials", {}) or {}
    html = html.replace("{{X}}", _esc(soc.get("x", "")))
    html = html.replace("{{BLUESKY}}", _esc(soc.get("bluesky", "")))
    html = html.replace("{{MESSAGE}}", _esc(d.get("badge_message", "")))
    br = int(round(max(0.15, min(1.0, d.get("brightness", 0.6))) * 100))
    html = html.replace("{{BRIGHTNESS}}", str(br))
    h24 = bool(d.get("clock_24h", True))
    html = html.replace("{{CLK24}}", "true" if h24 else "false")
    html = html.replace("{{CLK12}}", "false" if h24 else "true")
    return html.encode()


def on_save(form):
    # security gate: only someone looking at THIS badge knows the PIN
    if form.get("pin", "").strip() != PIN:
        raise ValueError("bad pin")
    ssid = (form.get("ssid_manual", "").strip() or form.get("ssid_select", "").strip())
    if ssid in ("Other…", "Other..."):
        ssid = form.get("ssid_manual", "").strip()
    pw = form.get("wifi_pass", "")
    upd = {"GITHUB_USERNAME": form.get("github", "").strip()}
    if ssid:
        upd["WIFI_SSID"] = ssid
        upd["WIFI_PASSWORD"] = pw
    set_secrets(upd)

    d = load_settings()
    d["linkedin_url"] = form.get("linkedin", "").strip()
    d["badge_message"] = form.get("message", "").strip()
    try:
        d["brightness"] = max(0.15, min(1.0, int(form.get("brightness", "60")) / 100.0))
    except ValueError:
        pass
    d["clock_24h"] = form.get("clock", "24") != "12"
    d["socials"] = {
        "x": form.get("x", "").strip().lstrip("@"),
        "bluesky": form.get("bluesky", "").strip().lstrip("@"),
    }
    try:
        fsutil.write_json(SETTINGS, d)        # atomic temp+rename
    except Exception as e:  # noqa: BLE001
        print("settings write err", e)

    if ssid:
        # secrets.py now exists (written just above), so the frozen wifi store
        # can import it safely — import lazily here, never at module load.
        try:
            import wifi as wm
            # Save WITHOUT guessing an auth mode. From the phone we can't know
            # which one works, and a wrong value (e.g. the AP's security=4) makes
            # the badge's wlan.connect(security=...) raise EINVAL. cyw43
            # auto-negotiates WPA2/WPA3 on a plain connect.
            wm.save_network(ssid, pw)
        except Exception as e:  # noqa: BLE001
            print("save_network err", e)
    # force the badge app to re-fetch the (possibly new) profile
    for f in ("/user_data.json", "/contrib_data.json", "/avatar.png"):
        try:
            os.remove(f)
        except OSError:
            pass


# Per-device hotspot identity, derived from the chip's globally-unique id
# (machine.unique_id(), 8 bytes) so it's stable per device and unique across the
# thousands of badges setting up at once.
#  - The AP NAME embeds the id TAIL (4 bytes) -> every badge is distinct.
#  - The PIN mixes the FULL id (FNV-1a hash) -> stable per device, and NOT
#    computable from the public AP name (which exposes only the tail bytes),
#    so a neighbour who sees your network still can't change your settings.
_UID = machine.unique_id()


def _uid_suffix(nbytes=4):
    return "".join("%02X" % b for b in _UID[-nbytes:])


def _derive_pin():
    h = 2166136261
    for b in _UID:                       # FNV-1a over all 8 id bytes
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return "%04d" % (h % 10000)


def _build_qr(text):
    q = qrcode.QRCode()
    q.set_text(text)
    size = q.get_size()[0]
    scale = max(1, 78 // (size + 2))
    pad = scale
    img = image(size * scale + pad * 2, size * scale + pad * 2)
    img.pen = color.rgb(255, 255, 255)
    img.rectangle(0, 0, img.width, img.height)
    img.pen = color.rgb(0, 0, 0)
    for y in range(size):
        for x in range(size):
            if q.get_module(x, y):
                img.rectangle(pad + x * scale, pad + y * scale, scale, scale)
    return img


# ---- bring-up: AP FIRST (broadcasts instantly), THEN scan + serve the page ----
_sta = network.WLAN(network.STA_IF)
_sta.active(True)
AP_SSID = "GH-Badge-" + _uid_suffix(4)  # unique per device (chip-id tail)
AP_PW = ""                              # OPEN network: cyw43 WPA2 fails to
                                        # associate on iOS, so we join open and
                                        # gate the SAVE with the PIN below
PIN = _derive_pin()                     # stable per device; not derivable from SSID

portal = Portal(AP_SSID, AP_PW, on_save)
portal.start_ap()                       # hotspot up immediately

qr_img = _build_qr("WIFI:T:nopass;S:%s;;" % AP_SSID)
QX = (160 - qr_img.width) // 2          # centered
QY = 28                                 # sits clear below the "Scan to set up" line

# scan (works while the AP is up) then build + start serving the page
_nets = scan_networks(_sta)

# Run the portal AP-ONLY from here on. Leaving the STA interface active during
# the portal made the badge HARD-REBOOT the instant a phone associated: the
# single-radio cyw43 servicing AP+STA concurrently, contending with the LCD
# render loop, faults (serial drops, no Python traceback, wake reason != 242).
# We only needed STA for the scan above, so shut it down now — the AP survives.
try:
    _sta.active(False)
except Exception:
    pass

portal.start_http(build_page(_nets))
saved_at = None


def _center(txt, y, pen):
    screen.font = small
    w, _ = screen.measure_text(txt)
    screen.pen = pen
    screen.text(txt, int(80 - w / 2), y)


def _header():
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 13))
    screen.font = small
    screen.pen = WHITE
    screen.text("Badge Setup", 4, 3)
    screen.pen = MUTED
    screen.text("HOME exit", 110, 3)


# ---- "join" view: scan the QR to hop onto the badge hotspot ----
def draw_join():
    _center("Scan to set up", 15, WHITE)
    screen.blit(qr_img, vec2(QX, QY))
    _center(AP_SSID, QY + qr_img.height + 4, LAV)
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 106, 160, 14))
    screen.font = tiny
    screen.pen = MUTED
    screen.text("Waiting for phone...", 6, 110)


# ---- "connected" view: a typing hacker terminal that ends on the PIN reveal ----
TERM = [
    ("> establishing connection", GREEN),
    ("> phone connected", GREEN),
    ("> link secured", GREEN),
    ("> open  192.168.4.1", WHITE),
    ("> re-establishing link", GREEN),
    ("> access granted", GREEN),
]
CHAR_MS = 24
LINE_PAUSE = 220
term_start = None


def draw_terminal(elapsed):
    y = 17
    t = elapsed
    done = True
    screen.font = tiny
    for ln, pen in TERM:
        full = len(ln)
        lt = full * CHAR_MS
        if t >= lt + LINE_PAUSE:
            shown = full
            t -= lt + LINE_PAUSE
            typing = False
        elif t > 0:
            shown = min(full, int(t // CHAR_MS))
            t = 0
            typing = True
            done = False
        else:
            done = False
            break
        txt = ln[:shown]
        screen.pen = pen
        screen.text(txt, 6, y)
        if typing and (badge.ticks // 300) % 2 == 0:
            cw = screen.measure_text(txt)[0]
            screen.shape(shape.rectangle(6 + cw + 1, y, 4, 8))
        y += 11
    # the reveal: PIN, big + boxed, once the sequence finishes
    if done:
        screen.pen = color.rgb(20, 60, 38)
        screen.shape(shape.rounded_rectangle(8, 90, 144, 26, 4))
        screen.pen = GREEN
        screen.shape(shape.rounded_rectangle(8, 90, 144, 1, 0))
        screen.font = big
        lbl = "PIN  " + PIN
        w, _ = screen.measure_text(lbl)
        screen.pen = LIME
        screen.text(lbl, int(80 - w / 2), 95)


def update():
    global saved_at, term_start
    portal.poll()

    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    _header()

    if portal.saved or saved_at:
        if not saved_at:
            saved_at = badge.ticks
        screen.pen = color.rgb(20, 60, 38)
        screen.shape(shape.rectangle(0, 106, 160, 14))
        screen.font = tiny
        screen.pen = GREEN
        screen.text("Saved! Restarting...", 6, 110)
        if badge.ticks - saved_at > 2500:
            portal.stop()
            machine.reset()
        return None

    if portal.num_clients():
        if term_start is None:
            term_start = badge.ticks
        draw_terminal(badge.ticks - term_start)
    else:
        term_start = None
        draw_join()
    return None


def on_exit():
    try:
        portal.stop()
    except Exception:
        pass


# --- custom run loop (replaces run(update)) ---------------------------------
# The badge HARD-REBOOTS if the LCD parallel-DMA (PIO1) is mid-transfer at the
# instant a phone associates to the cyw43 AP — a silicon-level DMA/IRQ
# contention (serial drops, no Python traceback, wake reason != watchdog).
# Mitigation: while we're idle on the STATIC join screen, push to the LCD only
# ONCE, then keep display.update() entirely off the bus until a phone is fully
# associated (num_clients() reads from ap.status("stations"), which only
# populates AFTER association completes). That removes the collision window.
# Once a client is on, association is already done, so we animate at full rate.
_idle_drawn = False
while True:
    portal.poll()
    active = bool(portal.num_clients() or portal.saved or saved_at)
    if active:
        badge.clear()
        if update() is not None:
            break
        display.update()
        _idle_drawn = False
    elif not _idle_drawn:
        badge.clear()
        update()
        display.update()
        _idle_drawn = True
    badge.poll()
