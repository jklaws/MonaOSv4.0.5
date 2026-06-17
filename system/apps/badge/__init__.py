import sys
import os

sys.path.insert(0, "/system/apps/badge")
os.chdir("/system/apps/badge")


import badgeware  # noqa: F401  (builtins: screen, color, shape, rect, vec2, mat3, image, pixel_font, badge, run)
screen.antialias = X2  # v2.0.2 upgrade: smooth anti-aliased rendering
from badgeware.filesystem import file_exists
import random
import math
import time
import network
from urllib.urequest import urlopen
import gc
import json
import qrcode


# Unified greens: the GitHub contribution-graph family, so EVERY green on the
# badge matches the heatmap instead of the old clashing lime + mismatched
# terminal greens.
GH_GREEN = color.rgb(57, 211, 83)     # #39d353  bright accent (handle, labels, terminal text)
GH_MID = color.rgb(38, 166, 65)       # #26a641  secondary (terminal prompt)
GH_DARK = color.rgb(14, 68, 41)       # #0e4429  dark line / border
phosphor = GH_GREEN                    # keep the name; now the GitHub green
white = color.rgb(235, 245, 255)
faded = color.rgb(235, 245, 255, 100)
small_font = pixel_font.load("/system/assets/fonts/ark.ppf")
large_font = pixel_font.load("/system/assets/fonts/absolute.ppf")
social_font = pixel_font.load("/system/assets/fonts/corpsavage.ppf")  # socials list + QR (lowercase, compact)

WIFI_TIMEOUT = 60
CONTRIB_URL = "https://github.com/{user}.contribs"
USER_AVATAR = "https://wsrv.nl/?url=https://github.com/{user}.png&w=75&output=png"
DETAILS_URL = "https://api.github.com/users/{user}"

WIFI_PASSWORD = None
WIFI_SSID = None
GITHUB_TOKEN = ""   # optional; raises GitHub API limit 60 -> 5000 req/hr

wlan = None
connected = False
ticks_start = None


def message(text):
    print(text)


def get_connection_details(user):
    global WIFI_PASSWORD, WIFI_SSID, GITHUB_TOKEN

    if WIFI_SSID is not None and user.handle is not None:
        return True

    try:
        sys.path.insert(0, "/")
        from secrets import WIFI_PASSWORD, WIFI_SSID, GITHUB_USERNAME
        import secrets as _s
        GITHUB_TOKEN = getattr(_s, "GITHUB_TOKEN", "") or ""   # optional
        sys.path.pop(0)
    except ImportError:
        WIFI_PASSWORD = None
        WIFI_SSID = None
        GITHUB_USERNAME = None

    if not WIFI_SSID:
        return False

    if not GITHUB_USERNAME:
        return False

    user.handle = GITHUB_USERNAME

    return True


def wlan_start():
    global wlan, ticks_start, connected, WIFI_PASSWORD, WIFI_SSID

    if ticks_start is None:
        ticks_start = badge.ticks

    if connected:
        return True

    if wlan is None:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)

        if wlan.isconnected():
            return True

        # Auto-join: prefer the strongest saved network in range (from the WiFi
        # app's /wifi.json), using the auth mode the WiFi app discovered works.
        # Falls back to the secrets.py values (WPA2) when none saved.
        _auth = None
        try:
            import wifi as _wifi
            pick = _wifi.best_saved_in_range()
            if pick:
                WIFI_SSID, WIFI_PASSWORD, _auth = pick
        except Exception:
            pass

        try:
            if _auth is None:
                wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            else:
                wlan.connect(WIFI_SSID, WIFI_PASSWORD, security=_auth)
        except (OSError, ValueError, TypeError):
            # A stored auth mode the firmware rejects (EINVAL) must NEVER crash
            # the badge. Fall back to a plain connect — cyw43 auto-negotiates
            # WPA2/WPA3, which works for virtually every network.
            try:
                wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            except Exception:
                pass

        print("Connecting to WiFi...")

    connected = wlan.isconnected()

    if badge.ticks - ticks_start < WIFI_TIMEOUT * 1000:
        if connected:
            return True
    elif not connected:
        return False

    return True


def async_fetch_to_disk(url, file, force_update=False):
    if not force_update and file_exists(file):
        return
    try:
        # Grab the data
        hdrs = {"User-Agent": "GitHub Universe Badge 2025"}
        # authenticate GitHub requests (not the wsrv.nl avatar proxy) when a token
        # is configured, raising the rate limit from 60 to 5000 requests/hour
        if GITHUB_TOKEN and (url.startswith("https://api.github.com") or url.startswith("https://github.com")):
            hdrs["Authorization"] = "Bearer " + GITHUB_TOKEN
        response = urlopen(url, headers=hdrs)
        data = bytearray(512)
        total = 0
        # stream to a temp file, then rename — a failed/partial download never
        # leaves a corrupt cache file that later json.loads would choke on
        tmp = file + ".part"
        with open(tmp, "wb") as f:
            while True:
                if (length := response.readinto(data)) == 0:
                    break
                total += length
                message(f"Fetched {total} bytes")
                f.write(data[:length])
                yield
        os.rename(tmp, file)
        del data
        del response
    except Exception as e:
        try:
            os.remove(file + ".part")
        except OSError:
            pass
        raise RuntimeError(f"Fetch from {url} to {file} failed. {e}") from e


def get_user_data(user, force_update=False):
    message(f"Getting user data for {user.handle}...")
    yield from async_fetch_to_disk(DETAILS_URL.format(user=user.handle), "/user_data.json", force_update)
    with open("/user_data.json", "r") as _f:
        r = json.loads(_f.read())
    # GitHub returns an error object (no "login") when rate-limited or the user
    # doesn't exist. Drop the bad cache and surface a clean message instead of
    # crashing on a missing key.
    if "login" not in r:
        try:
            os.remove("/user_data.json")
        except OSError:
            pass
        raise RuntimeError(r.get("message", "GitHub API error"))
    # GitHub "name" can be null (no display name set); fall back to the login so
    # the loaded-check (name is None) doesn't loop forever.
    user.name = r["name"] or r["login"]
    user.handle = r["login"]
    user.followers = r["followers"]
    user.repos = r["public_repos"]
    del r
    gc.collect()


def get_contrib_data(user, force_update=False):
    message(f"Getting contribution data for {user.handle}...")
    yield from async_fetch_to_disk(CONTRIB_URL.format(user=user.handle), "/contrib_data.json", force_update)
    with open("/contrib_data.json", "r") as _f:
        r = json.loads(_f.read())
    if "total_contributions" not in r:
        try:
            os.remove("/contrib_data.json")
        except OSError:
            pass
        raise RuntimeError(r.get("message", "GitHub contribs error"))
    user.contribs = r["total_contributions"]
    user.contribution_data = [[0 for _ in range(53)] for _ in range(7)]
    for w, week in enumerate(r["weeks"]):
        for day in range(7):
            try:
                user.contribution_data[day][w] = week["contribution_days"][day]["level"]
            except IndexError:
                pass
    del r
    gc.collect()


def get_avatar(user, force_update=False):
    message(f"Getting avatar for {user.handle}...")
    yield from async_fetch_to_disk(USER_AVATAR.format(user=user.handle), "/avatar.png", force_update)
    try:
        user.avatar = image.load("/avatar.png")
    except Exception:
        try:
            os.remove("/avatar.png")
        except OSError:
            pass
        raise RuntimeError("Avatar load failed")


def placeholder_if_none(text):
    if text:
        return text
    random.seed(int(badge.ticks / 100))
    chars = "!\"£$%^&*()_+-={}[]:@~;'#<>?,./\\|"
    out = ""
    for _ in range(20):
        out += random.choice(chars)
    return out


def _load_term_msgs():
    # messages the terminal cycles through; a user-set custom string (Settings >
    # Badge message) comes first, then the event branding + date/location.
    msgs = []
    try:
        import json as _json
        cm = _json.load(open("/settings.json")).get("badge_message", "")
        if cm and cm.strip():
            msgs.append(cm.strip())
    except Exception:
        pass
    msgs.append("UNIVERSE '26")
    msgs.append("Oct 28 - 29")
    msgs.append("Fort Mason Center")
    msgs.append("San Francisco, CA")
    return msgs


TERM_MSGS = _load_term_msgs()


class User:
    levels = [
        color.rgb(int(21 / 2),  int(27 / 2),  int(35 / 2)),
        color.rgb(int(3 / 2),  int(58 / 2),  int(22 / 2)),
        color.rgb(int(25 / 2), int(108 / 2),  int(46 / 2)),
        color.rgb(int(46 / 2), int(160 / 2),  int(67 / 2)),
        color.rgb(int(86 / 2), int(211 / 2), int(100 / 2)),
    ]
    # brighter palette used where the animated shimmer wave passes over a cell
    # (level 0 is green-tinted so the sweep is visible even on an empty graph)
    shimmer = [
        color.rgb(34, 78, 52),
        color.rgb(40, 140, 74),
        color.rgb(60, 188, 104),
        color.rgb(110, 232, 140),
        color.rgb(165, 255, 195),
    ]

    def __init__(self):
        self.handle = None
        self.update()

    def update(self, force_update=False):
        self.name = None
        self.followers = None
        self.contribs = None
        self.contribution_data = None
        self.repos = None
        self.avatar = None
        self._task = None
        self._force_update = force_update
        self._error = None

    def _fmt(self, n):
        # compact large numbers so they never overflow (128, 12.3k, 100k, 1.2M)
        if n is None:
            return "--"
        n = int(n)
        if n < 1000:
            return str(n)
        if n < 1000000:
            v = n / 1000.0
            return ("%.1fk" % v) if v < 10 else ("%dk" % round(v))
        v = n / 1000000.0
        return ("%.1fM" % v) if v < 10 else ("%dM" % round(v))

    # right-aligned numbers end here; labels start at a fixed x so they never
    # shift when the numbers load
    NUM_RIGHT = 92
    LABEL_X = 96

    def _stat_row(self, value, label, y):
        screen.font = small_font
        num = self._fmt(value)
        nw, _ = screen.measure_text(num)
        screen.pen = white if value is not None else faded
        screen.text(num, User.NUM_RIGHT - nw, y)   # right-aligned numbers
        screen.pen = phosphor
        screen.text(label, User.LABEL_X, y)         # fixed-position labels

    def _draw_terminal(self):
        # single-line terminal status bar that cycles messages, typing each out
        BY = 104
        screen.pen = color.rgb(7, 18, 12)            # dark green-tinted panel
        screen.shape(shape.rectangle(0, 96, 160, 24))
        screen.pen = GH_DARK                         # top border, GH green family
        screen.shape(shape.rectangle(0, 96, 160, 1))

        # on the event day the terminal just shows "GitHub Universe"
        try:
            lt = time.localtime()
            event_day = (lt[1] == 10 and lt[2] == 28)
        except Exception:
            event_day = False
        msgs = ["GitHub Universe"] if event_day else TERM_MSGS

        PER, HOLD = 70, 1700
        durs = [len(m) * PER + HOLD for m in msgs]
        total = 0
        for d in durs:
            total += d
        tcur = badge.ticks % total
        idx = 0
        while tcur >= durs[idx]:
            tcur -= durs[idx]
            idx += 1
        msg = msgs[idx]
        reveal = int(tcur / PER)
        if reveal > len(msg):
            reveal = len(msg)
        shown = msg[:reveal]

        screen.font = small_font
        prompt = "> "
        pw, _ = screen.measure_text(prompt)
        avail = 150 - pw
        text = shown
        while text and screen.measure_text(text)[0] > avail:
            text = text[1:]                 # scroll: keep the tail when too long
        screen.pen = GH_MID
        screen.text(prompt, 6, BY)
        screen.pen = GH_GREEN
        screen.text(text, 6 + pw, BY)
        if (badge.ticks // 350) % 2 == 0:   # blinking cursor
            tw, _ = screen.measure_text(text)
            screen.shape(shape.rectangle(6 + pw + tw + 1, BY, 4, 9))

    def _rt(self, s, fnt, pen, y, right=156):
        screen.font = fnt
        w, _ = screen.measure_text(s)
        screen.pen = pen
        screen.text(s, int(right - w), y)

    def draw(self, connected):
        # ---- drive the fetch (load data, handle errors gracefully) ----
        status = None
        if (self.handle is None or self.avatar is None or self.contribs is None) and connected and not self._error:
            if self.name is None:
                status = "fetching profile..."
                if not self._task:
                    self._task = get_user_data(self, self._force_update)
            elif self.contribs is None:
                status = "fetching contribs..."
                if not self._task:
                    self._task = get_contrib_data(self, self._force_update)
            else:
                status = "fetching avatar..."
                if not self._task:
                    self._task = get_avatar(self, self._force_update)
            try:
                next(self._task)
            except StopIteration:
                self._task = None
            except Exception as e:  # noqa: BLE001
                self._task = None
                msg = str(e)
                self._error = "Rate limit - A+C retry" if "rate limit" in msg.lower() else (msg[:22] + " - A+C")
        if not connected:
            status = "connecting..."

        # ---- avatar (large, left) or loading spinner ----
        AV = 62
        if self.avatar:
            screen.blit(self.avatar, rect(4, 5, AV, AV))
        else:
            screen.pen = color.rgb(57, 211, 83, 50)   # faded GitHub green
            sq = shape.squircle(0, 0, 10, 5)
            for i in range(4):
                mul = math.sin(badge.ticks / 1000) * 14000
                sq.transform = mat3().translate(35, 36).rotate(
                    (badge.ticks + i * mul) / 40).scale(1 + i / 1.3)
                screen.shape(sq)

        # ---- name + handle (right-aligned) ----
        if self.name is None:
            self._rt(status or "", small_font, white, 12)
        else:
            nm = self.name
            f = large_font
            screen.font = f
            if screen.measure_text(nm)[0] > 82:
                f = small_font
            self._rt(nm, f, white, 6)
            if self._error:
                self._rt(self._error, small_font, color.rgb(240, 110, 110), 22)
            else:
                hh = self.handle or ""
                self._rt(hh if hh.startswith("@") else "@" + hh, small_font, phosphor, 22)

        # ---- stats (right-aligned numbers, fixed labels) ----
        self._stat_row(self.followers, "followers", 38)
        self._stat_row(self.contribs, "contribs", 50)
        self._stat_row(self.repos, "repos", 62)

        # ---- contribution heatmap band (3 rows, evolving animated pattern) ----
        # an ever-changing pseudo-random field (3 sines at different freqs/phases)
        # twinkles in place; no scrolling grid, no sweep bar. Real contribution
        # activity still punches through as brighter cells.
        GY, sz, pitch = 80, 3, 4
        cols = 160 // pitch
        t = badge.ticks
        cd = self.contribution_data
        cell = shape.rounded_rectangle(0, 0, sz, sz, 1)
        for gy in range(3):
            for gx in range(cols):
                v = (math.sin(gx * 0.9 + t * 0.0017)
                     + math.sin(gy * 1.7 - t * 0.0023)
                     + math.sin((gx * 3 + gy) * 0.7 + t * 0.0029))
                lvl = int((v + 3.0) / 6.0 * 5)
                lvl = 0 if lvl < 0 else (4 if lvl > 4 else lvl)
                if cd:                       # let real activity show through
                    if gy == 0:
                        rl = max(cd[0][gx], cd[1][gx])
                    elif gy == 1:
                        rl = max(cd[2][gx], cd[3][gx])
                    else:
                        rl = max(cd[4][gx], cd[5][gx], cd[6][gx])
                    if rl > lvl:
                        lvl = rl
                screen.pen = User.levels[lvl]
                cell.transform = mat3().translate(gx * pitch, GY + gy * pitch)
                screen.shape(cell)

        # ---- terminal status bar ----
        self._draw_terminal()


user = User()
connected = file_exists("/contrib_data.json") and file_exists("/user_data.json") and file_exists("/avatar.png")
force_update = False


def center_text(text, y):
  w, h = screen.measure_text(text)
  screen.text(text, int(80 - (w / 2)), int(y))


def wrap_text(text, x, y):
  lines = text.splitlines()
  for line in lines:
    _, h = screen.measure_text(line)
    screen.text(line, int(x), int(y))
    y += h * 0.8


# tell the user where to fill in their details
def no_secrets_error():
  screen.font = large_font
  screen.pen = white
  center_text("Let's set up!", 5)

  screen.text("1:", 10, 23)
  screen.text("2:", 10, 55)
  screen.text("3:", 10, 87)

  screen.pen = phosphor
  screen.font = small_font
  wrap_text("""Press B to open\nSetup""", 30, 24)

  wrap_text("""Scan the QR, then\nadd WiFi + GitHub\non your phone""", 30, 56)

  wrap_text("""Reload to see your\nsweet sweet stats!""", 30, 88)


# tell the user that the connection failed :-(
def connection_error():
  screen.font = large_font
  screen.pen = white
  center_text("Connection Failed!", 5)

  screen.text("1:", 10, 63)
  screen.text("2:", 10, 95)

  screen.pen = phosphor
  screen.font = small_font
  wrap_text("""Could not connect\nto the WiFi network.\n\n:-(""", 16, 20)

  wrap_text("""Open the WiFi app\nto join or switch\nnetworks.""", 30, 65)

  wrap_text("""Reload to see your\nsweet sweet stats!""", 30, 96)


# ---------------------------------------------------------------------------
# Socials drill-down: B flips the profile to a list of your socials; UP/DOWN
# select; B again shows that social's QR (scan to connect); A backs out.
# Handles: GitHub from secrets.py, LinkedIn from settings.linkedin_url, and
# X/Bluesky/YouTube from settings.socials (written by the phone Setup app).
# No WiFi needed — these are just handles -> URLs -> QR.
# ---------------------------------------------------------------------------
V_PROFILE, V_SOCIALS, V_QR = 0, 1, 2
view = V_PROFILE
sel = 0
_socials_cache = []
_qr = None            # (url, image) — cached so we don't rebuild the QR each frame
_icons = {}


def _icon(plat):
    if plat not in _icons:
        try:
            _icons[plat] = image.load("/system/apps/badge/assets/socials/%s.png" % plat)
        except Exception:
            _icons[plat] = None
    return _icons[plat]


def _gh_user():
    try:
        sys.path.insert(0, "/")
        from secrets import GITHUB_USERNAME as g
        return (g or "").strip()
    except Exception:
        return ""
    finally:
        try:
            sys.path.pop(0)
        except Exception:
            pass


def _socials_list():
    # [(platform, display_handle, url)] for every social that has a value
    try:
        d = json.load(open("/settings.json"))
    except Exception:
        d = {}
    soc = d.get("socials", {}) or {}
    out = []

    gh = _gh_user().lstrip("@")
    if gh:
        out.append(("github", gh, "https://github.com/" + gh))

    li = (d.get("linkedin_url", "") or "").strip()
    if li:
        if li.startswith("http"):
            url, h = li, li.rstrip("/").split("/")[-1]
        else:
            h = li.strip("/")
            url = "https://www.linkedin.com/in/" + h + "/"
        out.append(("linkedin", h, url))

    x = (soc.get("x", "") or "").strip().lstrip("@")
    if x:
        out.append(("x", "@" + x, "https://x.com/" + x))

    bs = (soc.get("bluesky", "") or "").strip().lstrip("@")
    if bs:
        out.append(("bluesky", bs, "https://bsky.app/profile/" + bs))

    return out


def _build_qr(text, target=96):
    q = qrcode.QRCode()
    q.set_text(text)
    size = q.get_size()[0]
    scale = max(2, target // (size + 2))
    pad = scale
    dim = size * scale + pad * 2
    img = image(dim, dim)
    img.pen = color.rgb(255, 255, 255)
    img.rectangle(0, 0, dim, dim)
    img.pen = color.rgb(0, 0, 0)
    for yy in range(size):
        for xx in range(size):
            if q.get_module(xx, yy):
                img.rectangle(pad + xx * scale, pad + yy * scale, scale, scale)
    return img


def draw_socials(items, isel):
    # Tufty-style: an icon "chip" + handle per row (4 socials). A handle too wide
    # for its row is clipped and SCROLLS (marquee); ones that fit sit static.
    ROW = 21
    HX, AVAIL = 44, 112              # handle area: x 44 .. 156
    y = 14
    for i, (plat, handle, url) in enumerate(items):
        sel = (i == isel)
        if sel:
            screen.pen = GH_DARK
            screen.shape(shape.rounded_rectangle(8, y - 2, 144, ROW - 1, 4))
        screen.pen = GH_MID if sel else color.rgb(55, 62, 70)
        screen.shape(shape.rounded_rectangle(20, y, 17, 17, 3))
        ic = _icon(plat)
        if ic:
            screen.blit(ic, vec2(20, y))
        # handle — Crisp for every row (compact, correct lowercase); scroll it
        # (marquee) only when it's too wide for the row.
        screen.font = social_font
        pen = GH_GREEN if sel else white
        w = screen.measure_text(handle)[0]
        hy = y + 4
        if w <= AVAIL:
            screen.pen = pen
            screen.text(handle, HX, hy)
        else:
            period = w + 18
            off = (badge.ticks // 28) % period
            screen.clip = rect(HX, y, AVAIL, ROW)
            screen.pen = pen
            screen.text(handle, HX - off, hy)
            screen.text(handle, HX - off + period, hy)   # seamless wrap
            screen.clip = rect(0, 0, 160, 120)
        y += ROW
    screen.pen = faded
    screen.font = social_font
    # align each label over its physical button: A (left ~17), B (mid ~68),
    # UP/DOWN to the right. Was one string with A:back stuck on the right.
    screen.text("A:back", 14, 112)
    screen.text("B:QR", 65, 112)
    screen.text("UP/DN", 110, 112)


def draw_qr(item):
    global _qr
    plat, handle, url = item
    if _qr is None or _qr[0] != url:
        _qr = (url, _build_qr(url))
    img = _qr[1]
    qx = (160 - img.width) // 2
    qy = max(3, (102 - img.height) // 2)
    screen.blit(img, vec2(qx, qy))
    ly = qy + img.height + 3
    screen.font = social_font
    hw = screen.measure_text(handle)[0]
    x0 = (160 - (18 + hw)) // 2
    ic = _icon(plat)
    if ic:
        screen.blit(ic, vec2(x0, ly))
    screen.pen = GH_GREEN
    screen.text(handle, x0 + 18, ly + 4)


def update():
    global connected, force_update, view, sel, _socials_cache, _qr

    screen.pen = color.rgb(0, 0, 0)
    screen.shape(shape.rectangle(0, 0, 160, 120))

    force_update = False

    # Not set up yet? Show the prompt; B opens Setup directly. update() can
    # return another app's PATH and the launcher (/system/main.py) chains to it.
    if not get_connection_details(user):
        view = V_PROFILE
        if badge.pressed(BUTTON_B):
            return "/system/apps/setup"
        no_secrets_error()
        return

    # ---- B / A / UP / DOWN drive the socials drill-down ----
    if view == V_PROFILE:
        if badge.pressed(BUTTON_B):
            _socials_cache = _socials_list()
            if _socials_cache:
                view = V_SOCIALS
                sel = 0
    elif view == V_SOCIALS:
        n = len(_socials_cache)
        if n == 0:
            view = V_PROFILE
        else:
            sel %= n
            if badge.pressed(BUTTON_UP):
                sel = (sel - 1) % n
            if badge.pressed(BUTTON_DOWN):
                sel = (sel + 1) % n
            if badge.pressed(BUTTON_A):
                view = V_PROFILE
            if badge.pressed(BUTTON_B):
                view = V_QR
                _qr = None

    elif view == V_QR:
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_B):
            view = V_SOCIALS
            _qr = None

    if view == V_SOCIALS:
        draw_socials(_socials_cache, sel)
        return
    if view == V_QR:
        if sel < len(_socials_cache):
            draw_qr(_socials_cache[sel])
        else:
            view = V_SOCIALS
            draw_socials(_socials_cache, sel)
        return

    # ---- profile view (we're configured here) ----
    if badge.held(BUTTON_A) and badge.held(BUTTON_C):
        connected = False
        user.update(True)

    if wlan_start():
        user.draw(connected)
    else:  # Connection Failed
        connection_error()


# v2.0.2 launch() contract: apps run at import. Capture run().result into on_exit
# so a path returned from update() (e.g. "/system/apps/setup" on the B shortcut)
# is surfaced through launch() and the launcher chains to it.
on_exit = run(update).result
