import sys
import os

sys.path.insert(0, "/system/apps/settings")
os.chdir("/system/apps/settings")

import badgeware  # noqa: F401  (builtins: screen, color, shape, vec2, pixel_font, badge, run, BUTTON_*)
from badgeware import set_brightness
import json
import time

Keyboard = __import__("/system/keyboard").Keyboard
fsutil = __import__("/system/fsutil")     # atomic, crash-safe file writes

screen.antialias = X2

small = pixel_font.load("/system/assets/fonts/ark.ppf")   # one consistent UI font

BG = color.rgb(24, 26, 30)
PANEL = color.rgb(40, 44, 52)
HILITE = color.rgb(211, 250, 55)
HITEXT = color.rgb(20, 24, 16)
WHITE = color.rgb(235, 245, 255)
FADED = color.rgb(235, 245, 255, 110)
GOOD = color.rgb(120, 230, 120)
BAD = color.rgb(240, 110, 110)

SETTINGS = "/settings.json"
SECRETS = "/secrets.py"
MIN_B = 0.15
B_STEP = 0.05
TZ_STEP = 0.5
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings():
    try:
        fsutil.write_json(SETTINGS, data)      # atomic temp+rename
    except Exception:
        pass


def load_github_user():
    try:
        with open(SECRETS) as f:
            for ln in f:
                if ln.strip().startswith("GITHUB_USERNAME"):
                    return ln.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return ""


def save_github_user(name):
    lines = fsutil.read_text(SECRETS).split("\n")
    if lines == [""]:
        lines = []
    newline = "GITHUB_USERNAME = %r" % name
    done = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("GITHUB_USERNAME"):
            lines[i] = newline
            done = True
            break
    if not done:
        lines.append(newline)
    try:
        fsutil.write_text(SECRETS, "\n".join(lines))   # atomic temp+rename
    except Exception:
        pass


data = load_settings()
brightness = max(MIN_B, min(1.0, data.get("brightness", 0.6)))
tz = data.get("tz_offset", 0.0)
clock_24h = bool(data.get("clock_24h", True))
gh_user = load_github_user()
badge_msg = data.get("badge_message", "")
linkedin_url = data.get("linkedin_url", "")
set_brightness(brightness)

ITEMS = ("Brightness", "Time zone", "Clock", "Sync time", "GitHub user",
         "Badge message", "LinkedIn")
sel = 0
kb = None                 # active Keyboard instance when editing text
kb_field = None           # which field the keyboard is editing
sync_status = ""
sync_color = FADED
dirty_at = 0              # ticks of last brightness/tz/clock change (debounced save)


def fmt_tz(o):
    sign = "+" if o >= 0 else "-"
    a = abs(o)
    h = int(a)
    m = int(round((a - h) * 60))
    return "UTC%s%d:%02d" % (sign, h, m)


def fmt_hm(h, m):
    # honours the 12h / 24h preference
    if clock_24h:
        return "%02d:%02d" % (h, m)
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return "%d:%02d %s" % (h12, m, ap)


def sync_time():
    global sync_status, sync_color
    import network
    import wifi
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if not w.isconnected():
        pick = wifi.best_saved_in_range()
        if not pick:
            sync_status = "No saved WiFi"
            sync_color = BAD
            return
        ssid, psk, auth = pick
        if auth is None:
            w.connect(ssid, psk)
        else:
            w.connect(ssid, psk, security=auth)
        t0 = time.ticks_ms()
        while not w.isconnected() and time.ticks_diff(time.ticks_ms(), t0) < 12000:
            time.sleep_ms(300)
    if not w.isconnected():
        sync_status = "WiFi failed"
        sync_color = BAD
        return
    try:
        import ntptime
        ntptime.settime()
        off = int(round(tz * 3600))
        tm = time.localtime(time.time() + off)
        import machine
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
        import badgeware.rtc
        badgeware.rtc.RTC().localtime_to_rtc()
        sync_status = "Synced " + fmt_hm(tm[3], tm[4])
        sync_color = GOOD
    except Exception as e:  # noqa: BLE001
        sync_status = "NTP error"
        sync_color = BAD
        print("sync error", e)


def adjust(delta):
    # update live + mark dirty; the actual write is debounced (see update())
    # so holding A/C doesn't rewrite settings.json on every single press
    global brightness, tz, clock_24h, dirty_at
    if sel == 0:
        brightness = max(MIN_B, min(1.0, round((brightness + delta * B_STEP) * 100) / 100))
        set_brightness(brightness)
        data["brightness"] = brightness
    elif sel == 1:
        tz = max(-12.0, min(14.0, tz + delta * TZ_STEP))
        data["tz_offset"] = tz
    elif sel == 2:
        clock_24h = not clock_24h          # 2-state toggle (either direction flips)
        data["clock_24h"] = clock_24h
    dirty_at = badge.ticks


def row(y, idx, label, value, val_pen=WHITE, val_font=small):
    active = idx == sel
    screen.pen = HILITE if active else PANEL
    screen.shape(shape.rounded_rectangle(4, y, 152, 12, 3))
    screen.font = small
    screen.pen = HITEXT if active else WHITE
    screen.text(label, 9, y + 3)
    screen.font = val_font
    screen.pen = HITEXT if active else val_pen
    w, _ = screen.measure_text(value)
    if w > 80:                      # truncate long values
        while value and screen.measure_text(value + "…")[0] > 80:
            value = value[:-1]
        value = value + "…"
        w, _ = screen.measure_text(value)
    screen.text(value, 151 - w, y + 3)


def update():
    global sel, kb, kb_field, gh_user, badge_msg, linkedin_url, sync_status, sync_color, dirty_at

    # debounced flush: save ~0.5s after the last brightness/tz/clock change
    if dirty_at and badge.ticks - dirty_at > 500:
        save_settings()
        dirty_at = 0

    if kb is not None:
        kb.update()
        if kb.done:
            val = kb.text.strip()
            if kb_field == "gh_user":
                if val != gh_user:
                    # invalidate the badge app's cached profile so it re-fetches
                    for f in ("/user_data.json", "/contrib_data.json", "/avatar.png"):
                        try:
                            os.remove(f)
                        except OSError:
                            pass
                    gh_user = val
                    save_github_user(val)     # only rewrite secrets.py on change
            elif kb_field == "badge_msg":
                badge_msg = val
                data["badge_message"] = val
                save_settings()
            elif kb_field == "linkedin":
                linkedin_url = val
                data["linkedin_url"] = val
                save_settings()
            kb = None
            kb_field = None
        return

    if badge.pressed(BUTTON_UP):
        sel = (sel - 1) % len(ITEMS)
    if badge.pressed(BUTTON_DOWN):
        sel = (sel + 1) % len(ITEMS)
    if badge.pressed(BUTTON_A):
        adjust(-1)
    if badge.pressed(BUTTON_C):
        adjust(1)
    if badge.pressed(BUTTON_B):
        if sel == 3:
            sync_status = "Syncing..."
            sync_color = FADED
            _draw()
            display.update()
            sync_time()
        elif sel == 4:
            kb = Keyboard("GitHub username", gh_user)
            kb_field = "gh_user"
        elif sel == 5:
            kb = Keyboard("Badge message", badge_msg)
            kb_field = "badge_msg"
        elif sel == 6:
            kb = Keyboard("LinkedIn name", linkedin_url)
            kb_field = "linkedin"

    _draw()


def _draw():
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))

    # header
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 13))
    screen.font = small
    screen.pen = WHITE
    screen.text("Settings", 4, 3)
    screen.pen = FADED
    hint = "HOME exit"
    w, _ = screen.measure_text(hint)
    screen.text(hint, 156 - w, 3)

    # rows
    row(15, 0, "Brightness", "%d%%" % int(round(brightness * 100)))
    row(28, 1, "Time zone", fmt_tz(tz))
    row(41, 2, "Clock", "24h" if clock_24h else "12h")
    sv = sync_status if sync_status else "press B"
    row(54, 3, "Sync time", sv, sync_color if sync_status else FADED)
    gv = gh_user if gh_user else "(set)"
    row(67, 4, "GitHub user", gv, WHITE if gh_user else FADED)
    bm = badge_msg if badge_msg else "(none)"
    row(80, 5, "Badge msg", bm, WHITE if badge_msg else FADED)
    lv = linkedin_url if linkedin_url else "(set)"
    row(93, 6, "LinkedIn", lv, WHITE if linkedin_url else FADED)

    # clock
    screen.font = small
    t = time.localtime()
    screen.pen = WHITE
    screen.text(fmt_hm(t[3], t[4]), 6, 108)
    screen.pen = FADED
    datestr = "%s %s %d" % (DAYS[t[6]], MONTHS[t[1]], t[2])
    w, _ = screen.measure_text(datestr)
    screen.text(datestr, 151 - w, 108)


run(update)
