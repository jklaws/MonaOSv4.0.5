import sys
import os

sys.path.insert(0, "/system/apps/wifi")
os.chdir("/system/apps/wifi")

import badgeware  # noqa: F401  (builtins: screen, color, shape, rect, vec2, pixel_font, badge, run, BUTTON_*)
import network
import time
# frozen shared store: saved_networks/save_network/forget_network. It does
# `import secrets` internally, which raises on a fresh/wiped device with no
# secrets.py — so guard it (main.py self-heals secrets.py at boot, but never
# crash the WiFi app if that hasn't happened). Fall back to a no-op store that
# satisfies every attribute this app touches (incl. the module-level AUTH_CYCLE
# / SEC_* below) so the app still opens and can scan.
try:
    import wifi as wm
except Exception:
    class _NoStore:
        AUTH_CYCLE = (None,)
        SEC_WPA2_WPA3 = 1
        SEC_WPA3 = 2

        @staticmethod
        def saved_networks():
            return []

        @staticmethod
        def save_network(*a, **k):
            pass

        @staticmethod
        def forget_network(*a, **k):
            pass

    wm = _NoStore()
_fsutil = __import__("/system/fsutil")     # atomic, crash-safe writes

screen.antialias = X2

# Typography hierarchy for a 160x120 panel:
#  - keys / password / mode badge use 'nope' (the most compact font that still
#    distinguishes upper vs lowercase — essential for entering a password)
#  - chrome (titles, hints, list rows) uses the slimmer 'ark' to stay compact
small = pixel_font.load("/system/assets/fonts/nope.ppf")
chrome = pixel_font.load("/system/assets/fonts/ark.ppf")
big = pixel_font.load("/system/assets/fonts/absolute.ppf")

BG = color.rgb(24, 26, 30)
PANEL = color.rgb(40, 44, 52)
HILITE = color.rgb(211, 250, 55)        # badge phosphor green
HITEXT = color.rgb(20, 24, 16)
WHITE = color.rgb(235, 245, 255)
FADED = color.rgb(235, 245, 255, 110)
GOOD = color.rgb(120, 230, 120)
BAD = color.rgb(240, 110, 110)
STAR = color.rgb(255, 205, 70)
ON_COLOR = color.rgb(235, 150, 40)       # active toggle (shift/sym/show)

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# seed the store once from an existing secrets.py network so it auto-joins too
try:
    if not wm.saved_networks():
        import secrets
        if getattr(secrets, "WIFI_SSID", ""):
            wm.save_network(secrets.WIFI_SSID, getattr(secrets, "WIFI_PASSWORD", ""))
except Exception:
    pass

# ---- state ------------------------------------------------------------------
SCAN, LIST, SAVED, KEYS, CONNECT, DONE = range(6)
state = SCAN
scan_frames = 0
nets = []                 # [(ssid, rssi, secured)]
saved_set = set()
sel = 0
top = 0
sv_sel = 0
sv_top = 0
ssid = ""
pw = ""
show_pw = False
kr = kc = 0
shift = syms = False
connect_started = 0
attempt = 0
result_ok = False
result_msg = ""

LOWER = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
UPPER = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
SYMBOLS = ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\".,/?\\|~`"]
ACTIONS = ["shift", "space", "sym", "show", "del", "ok"]
ALABEL = {"shift": "Aa", "space": "spc", "sym": "#%", "show": "eye", "del": "del", "ok": "OK"}
STATUS_MSG = {-1: "Connect failed", -2: "Network not found", -3: "Wrong password"}


def rows():
    return SYMBOLS if syms else (UPPER if shift else LOWER)


def refresh_saved():
    global saved_set
    saved_set = set(n.get("ssid", "") for n in wm.saved_networks())


def do_scan():
    found = {}
    try:
        for n in wlan.scan():
            name = n[0].decode("utf-8", "replace")
            # keep only printable chars; drops hidden/blank SSIDs (e.g. all-null
            # bytes) that would otherwise show as an unreadable empty row
            name = "".join(ch for ch in name if 32 <= ord(ch) <= 126)
            if not name.strip():
                continue
            rssi, secured = n[3], n[4] != 0
            if name not in found or rssi > found[name][1]:
                found[name] = (name, rssi, secured)
    except Exception as e:  # noqa: BLE001
        print("scan error", e)
    out = list(found.values())
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def bars_for(rssi):
    if rssi >= -55:
        return 4
    if rssi >= -65:
        return 3
    if rssi >= -75:
        return 2
    if rssi >= -85:
        return 1
    return 0


def draw_signal(x, y, level, active=False):
    on = HITEXT if active else WHITE
    off = HITEXT if active else FADED
    for i in range(4):
        h = 2 + i * 2
        screen.pen = on if i < level else off
        screen.shape(shape.rectangle(x + i * 4, y + (8 - h), 3, h))


def header(title, hint=None):
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 13))
    screen.font = chrome
    screen.pen = WHITE
    screen.text(title, 4, 3)
    if hint:
        screen.pen = FADED
        w, _ = screen.measure_text(hint)
        screen.text(hint, 156 - w, 3)


def list_window(count, sel_i, top_i, visible):
    if sel_i < top_i:
        top_i = sel_i
    if sel_i >= top_i + visible:
        top_i = sel_i - visible + 1
    return top_i


# ---- available-network list -------------------------------------------------
def draw_list():
    global top
    header("WiFi networks", "HOME exit")
    screen.font = small
    row_h, visible = 17, 5
    top = list_window(len(nets), sel, top, visible)
    for i in range(top, min(len(nets), top + visible)):
        name, rssi, secured = nets[i]
        y = 16 + (i - top) * row_h
        active = i == sel
        screen.pen = HILITE if active else PANEL
        screen.shape(shape.rounded_rectangle(3, y, 154, row_h - 2, 3))
        if name in saved_set:
            screen.pen = HITEXT if active else STAR
            screen.text("*", 6, y + 3)
        screen.pen = HITEXT if active else WHITE
        label = name if len(name) <= 18 else name[:17] + "…"
        screen.text(label, 13, y + 3)
        if secured:
            screen.pen = HITEXT if active else FADED
            screen.text("L", 130, y + 3)
        draw_signal(140, y + 4, bars_for(rssi), active)
    screen.font = chrome
    screen.pen = FADED
    screen.text("B join   A saved   C rescan", 4, 111)


# ---- saved-network manager --------------------------------------------------
def draw_saved():
    global sv_top
    header("Saved networks", "HOME exit")
    screen.font = small
    saved = wm.saved_networks()
    row_h, visible = 17, 5
    if not saved:
        screen.pen = WHITE
        screen.text("None saved yet.", 6, 30)
        screen.font = chrome
        screen.pen = FADED
        screen.text("C back", 4, 111)
        return
    sv_top = list_window(len(saved), sv_sel, sv_top, visible)
    for i in range(sv_top, min(len(saved), sv_top + visible)):
        name = saved[i].get("ssid", "")
        y = 16 + (i - sv_top) * row_h
        active = i == sv_sel
        screen.pen = HILITE if active else PANEL
        screen.shape(shape.rounded_rectangle(3, y, 154, row_h - 2, 3))
        screen.pen = HITEXT if active else WHITE
        label = name if len(name) <= 22 else name[:21] + "…"
        screen.text(label, 8, y + 3)
        if i == 0:
            screen.pen = HITEXT if active else STAR
            screen.text("*", 146, y + 3)
    screen.font = chrome
    screen.pen = FADED
    screen.text("B join   A forget   C back", 4, 111)


# ---- keyboard ---------------------------------------------------------------
def draw_keys():
    header("Password: " + (ssid if len(ssid) <= 16 else ssid[:15] + "…"))
    screen.font = small
    screen.pen = PANEL
    screen.shape(shape.rounded_rectangle(3, 16, 154, 14, 3))
    shown = pw if show_pw else ("*" * len(pw))
    if len(shown) > 18:
        shown = "…" + shown[-17:]
    screen.pen = WHITE
    screen.text(shown + "_", 7, 18)
    # input-mode badge so caps state is never a surprise
    mode = "#%" if syms else ("ABC" if shift else "abc")
    screen.pen = ON_COLOR if (shift or syms) else FADED
    mw, _ = screen.measure_text(mode)
    screen.text(mode, 152 - mw, 18)

    grid = rows()
    # spread rows to fill the panel height: row pitch > key height leaves a clean
    # gap between rows (fills the dead space at the bottom without enlarging glyphs)
    y0, pitch, keyh = 32, 17, 14
    for r, line in enumerate(grid):
        cw = 152 / len(line)
        for c in range(len(line)):
            x = 4 + c * cw
            y = y0 + r * pitch
            active = (kr == r and kc == c)
            screen.pen = HILITE if active else PANEL
            screen.shape(shape.rounded_rectangle(int(x), y, int(cw) - 1, keyh, 2))
            screen.pen = HITEXT if active else WHITE
            ch = line[c]
            w, _ = screen.measure_text(ch)
            screen.text(ch, int(x + (cw - w) / 2), y + 1)

    ar = len(grid)
    y = y0 + ar * pitch
    cw = 152 / len(ACTIONS)
    for c in range(len(ACTIONS)):
        x = 4 + c * cw
        active = (kr == ar and kc == c)
        on = ((ACTIONS[c] == "shift" and shift)
              or (ACTIONS[c] == "sym" and syms)
              or (ACTIONS[c] == "show" and show_pw))
        if active:
            screen.pen = HILITE
        elif on:
            screen.pen = ON_COLOR        # toggle is active -> bright orange
        else:
            screen.pen = color.rgb(60, 66, 76)
        screen.shape(shape.rounded_rectangle(int(x), y, int(cw) - 1, keyh + 1, 2))
        screen.pen = HITEXT if (active or on) else WHITE
        lbl = ALABEL[ACTIONS[c]]
        if ACTIONS[c] == "shift" and shift:
            lbl = "aA"
        if ACTIONS[c] == "sym" and syms:
            lbl = "ab"
        if ACTIONS[c] == "show" and show_pw:
            lbl = "hid"
        w, _ = screen.measure_text(lbl)
        screen.text(lbl, int(x + (cw - w) / 2), y + 1)


def cur_cols():
    grid = rows()
    return len(grid[kr]) if kr < len(grid) else len(ACTIONS)


def activate():
    global pw, shift, syms, kr, show_pw
    grid = rows()
    if kr < len(grid):
        pw += grid[kr][kc]
        if shift:
            shift = False
        return
    action = ACTIONS[kc]
    if action == "shift":
        shift = not shift
    elif action == "space":
        pw += " "
    elif action == "sym":
        syms = not syms
        kr = min(kr, len(rows()))
    elif action == "show":
        show_pw = not show_pw
    elif action == "del":
        pw = pw[:-1]
    elif action == "ok":
        start_connect()


# ---- connect + save ---------------------------------------------------------
MAX_ATTEMPTS = len(wm.AUTH_CYCLE)         # one attempt per auth mode
AUTH_NAME = {None: "WPA2", wm.SEC_WPA2_WPA3: "WPA2/WPA3", wm.SEC_WPA3: "WPA3"}


def attempt_auth():
    return wm.AUTH_CYCLE[min(attempt - 1, len(wm.AUTH_CYCLE) - 1)]


def _begin_attempt():
    global connect_started
    auth = attempt_auth()
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
        wlan.active(True)
    except Exception:
        pass
    if auth is None:
        wlan.connect(ssid, pw)
    else:
        wlan.connect(ssid, pw, security=auth)
    connect_started = time.ticks_ms()


def start_connect():
    global state, attempt
    attempt = 1
    _begin_attempt()
    state = CONNECT


def update_secrets_primary():
    # keep secrets.py as a fallback + PRESERVE every existing key. Read it as
    # TEXT (line-based), NOT via import: a bad/partial file or a stale
    # sys.modules cache must never silently wipe GITHUB_USERNAME / GITHUB_TOKEN.
    keep = {}     # key -> RHS text (verbatim, already a valid literal)
    order = []
    try:
        for ln in open("/secrets.py"):
            s = ln.strip()
            if "=" in s and not s.startswith("#"):
                k = s.split("=", 1)[0].strip()
                if k and k not in keep:
                    keep[k] = s.split("=", 1)[1].strip()
                    order.append(k)
    except Exception:
        pass
    keep["WIFI_SSID"] = repr(ssid)        # update creds; everything else verbatim
    keep["WIFI_PASSWORD"] = repr(pw)
    for k in ("WIFI_SSID", "WIFI_PASSWORD", "GITHUB_USERNAME"):
        if k not in order:
            order.append(k)
    keep.setdefault("GITHUB_USERNAME", '""')
    try:
        body = "".join("%s = %s\n" % (k, keep[k]) for k in order)
        _fsutil.write_text("/secrets.py", body)    # atomic temp+rename
    except Exception:
        pass


def draw_connect():
    header("Connecting…")
    screen.font = big
    screen.pen = WHITE
    msg = "Connecting to"
    w, _ = screen.measure_text(msg)
    screen.text(msg, int(80 - w / 2), 40)
    w, _ = screen.measure_text(ssid)
    screen.pen = HILITE
    screen.text(ssid, int(80 - w / 2), 58)
    screen.font = small
    dots = "." * (1 + (badge.ticks // 400) % 3)
    screen.pen = FADED
    w, _ = screen.measure_text(dots)
    screen.text(dots, int(80 - w / 2), 80)
    a = "%s  (try %d/%d)" % (AUTH_NAME.get(attempt_auth(), "?"), attempt, MAX_ATTEMPTS)
    w, _ = screen.measure_text(a)
    screen.text(a, int(80 - w / 2), 92)


def _center(txt, y, pen, fnt):
    screen.font = fnt
    screen.pen = pen
    w, _ = screen.measure_text(txt)
    screen.text(txt, int(80 - w / 2), y)


def draw_done():
    header("WiFi setup")
    # headline: use the big font, but fall back to the smaller one if it would
    # overflow the 160px width (e.g. "Network not found")
    screen.font = big
    headline_font = big if screen.measure_text(result_msg)[0] <= 150 else small
    _center(result_msg, 28, GOOD if result_ok else BAD, headline_font)

    if result_ok:
        _center("Saved - will auto-join", 50, WHITE, chrome)
        try:
            ip = wlan.ifconfig()[0]
        except Exception:
            ip = ""
        if ip:
            _center(ip, 64, FADED, chrome)
    else:
        _center("B retry    C networks", 52, WHITE, chrome)

    # always tell the user how to leave
    _center("Press HOME to exit", 98, HILITE, chrome)


# ---- main loop --------------------------------------------------------------
def update():
    global state, scan_frames, nets, sel, sv_sel, ssid, pw, kr, kc, result_ok, result_msg, attempt

    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))

    if state == SCAN:
        header("Scanning for networks…")
        screen.font = small
        screen.pen = FADED
        screen.text("Looking for WiFi…", 4, 30)
        scan_frames += 1
        if scan_frames >= 2:
            refresh_saved()
            nets = do_scan()
            sel = 0
            state = LIST
        return

    if state == LIST:
        draw_list()
        if not nets:
            screen.pen = WHITE
            screen.text("No networks found.", 6, 40)
        if badge.pressed(BUTTON_UP):
            sel = (sel - 1) % max(1, len(nets))
        if badge.pressed(BUTTON_DOWN):
            sel = (sel + 1) % max(1, len(nets))
        if badge.pressed(BUTTON_A):
            sv_sel = 0
            state = SAVED
        elif badge.pressed(BUTTON_C):
            state = SCAN
            scan_frames = 0
        elif badge.pressed(BUTTON_B) and nets:
            name, _, secured = nets[sel]
            ssid = name
            stored = [n for n in wm.saved_networks() if n.get("ssid") == name]
            if stored:                       # already saved -> use stored password
                pw = stored[0].get("password", "")
                start_connect()
            elif not secured:                # open network
                pw = ""
                start_connect()
            else:
                pw = ""
                kr = kc = 0
                state = KEYS
        return

    if state == SAVED:
        draw_saved()
        saved = wm.saved_networks()
        if badge.pressed(BUTTON_UP) and saved:
            sv_sel = (sv_sel - 1) % len(saved)
        if badge.pressed(BUTTON_DOWN) and saved:
            sv_sel = (sv_sel + 1) % len(saved)
        if badge.pressed(BUTTON_C):
            state = LIST
        elif badge.pressed(BUTTON_A) and saved:
            wm.forget_network(saved[sv_sel].get("ssid", ""))
            refresh_saved()
            sv_sel = max(0, sv_sel - 1)
        elif badge.pressed(BUTTON_B) and saved:
            ssid = saved[sv_sel].get("ssid", "")
            pw = saved[sv_sel].get("password", "")
            start_connect()
        return

    if state == KEYS:
        draw_keys()
        if badge.pressed(BUTTON_UP):
            kr = (kr - 1) % (len(rows()) + 1)
            kc = min(kc, cur_cols() - 1)
        if badge.pressed(BUTTON_DOWN):
            kr = (kr + 1) % (len(rows()) + 1)
            kc = min(kc, cur_cols() - 1)
        if badge.pressed(BUTTON_A):
            kc = (kc - 1) % cur_cols()
        if badge.pressed(BUTTON_C):
            kc = (kc + 1) % cur_cols()
        if badge.pressed(BUTTON_B):
            activate()
        return

    if state == CONNECT:
        draw_connect()
        if wlan.isconnected():
            result_ok = True
            result_msg = "Connected!"
            wm.save_network(ssid, pw, attempt_auth())   # store the working auth
            update_secrets_primary()
            refresh_saved()
            state = DONE
            return
        try:
            st = wlan.status()
        except Exception:
            st = None
        # negative status codes are terminal errors. The CYW43 radio sometimes
        # reports a spurious -3 (wrong password) on the first try, so retry a few
        # times before believing it.
        if st is not None and st < 0:
            if attempt < MAX_ATTEMPTS:
                attempt += 1
                _begin_attempt()
            else:
                result_ok = False
                result_msg = STATUS_MSG.get(st, "Failed")
                state = DONE
        elif time.ticks_diff(time.ticks_ms(), connect_started) > 20000:
            if attempt < MAX_ATTEMPTS:
                attempt += 1
                _begin_attempt()
            else:
                result_ok = False
                result_msg = "Timed out"
                state = DONE
        return

    if state == DONE:
        draw_done()
        if badge.pressed(BUTTON_C):
            state = SCAN
            scan_frames = 0
        elif not result_ok and badge.pressed(BUTTON_B):
            kr = kc = 0
            state = KEYS
        return


run(update)
