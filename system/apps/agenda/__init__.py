import sys
import os

sys.path.insert(0, "/system/apps/agenda")
sys.path.insert(0, "/")
os.chdir("/system/apps/agenda")

import badgeware  # noqa: F401  (builtins: screen, color, shape, badge, run, BUTTON_*)
screen.antialias = X2
import time
import json

# Unified per-user badge repo + reboot-safe fetch (github.com/<handle>/badge).
ghbadge = __import__("/system/ghbadge")
fsutil = __import__("/system/fsutil")        # atomic, crash-safe cache writes
CACHE = "/state/agenda.json"                 # last synced agenda, survives reboot

# Single type FAMILY for a coherent look — hierarchy comes from SIZE, not from
# mixing faces (the corpsavage family is the only font in this app):
#   BODY  = corpsavage (h8) -> session titles, ALL CAPS (the heading tier)
#   SMALL = corpsavage (h8) -> brand mark, clock, day tab, times, subtitles, footer
#   corpsavage is our own 1-bit proportional pixel font (built from the MIT
#   petme128 8x8); titles use the same size but ALL CAPS to read as headings.
BODY = pixel_font.load("/system/assets/fonts/corpsavage.ppf")
SMALL = pixel_font.load("/system/assets/fonts/corpsavage.ppf")
FOOT = pixel_font.load("/system/assets/fonts/corpsavage.ppf")  # 8px footer (native master), mixed case, letter-spaced
H_BODY = 8
H_SMALL = 8
H_FOOT = 8
FOOT_TRACK = 1   # extra px between footer glyphs for breathing room


def _t(txt, x, y, font, pen):
    screen.font = font
    screen.pen = pen
    screen.text(txt, int(x), int(y))


def _w(txt, font):
    screen.font = font
    return screen.measure_text(txt)[0]


def _w_track(txt, font, track):
    # width of a letter-spaced string (extra `track` px between every glyph)
    screen.font = font
    if not txt:
        return 0
    return sum(screen.measure_text(c)[0] for c in txt) + track * (len(txt) - 1)


def _t_track(txt, x, y, font, pen, track):
    # draw letter-spaced text so small all-caps labels get breathing room
    screen.font = font
    screen.pen = pen
    cx = float(x)
    for ch in txt:
        screen.text(ch, int(cx), int(y))
        cx += screen.measure_text(ch)[0] + track

# honour the 12h/24h preference set in Settings > Clock
try:
    H24 = bool(json.load(open("/settings.json")).get("clock_24h", True))
except Exception:
    H24 = True

# ---- palette (OLED dark) ----
BG = color.rgb(13, 17, 23)
PANEL = color.rgb(26, 31, 40)
WHITE = color.rgb(238, 244, 250)
LAV = color.rgb(170, 140, 248)        # session times (matches the web)
GRAY = color.rgb(130, 144, 158)
GREEN = color.rgb(63, 200, 110)
GREENDK = color.rgb(20, 60, 38)
LIME = color.rgb(211, 250, 55)
ORANGE = color.rgb(240, 170, 70)

DEFAULT_EVENT = "GitHub Universe '26"
DEFAULT_YEAR = 2026

# Built-in fallback schedule, shown until the user syncs their own from
# github.com/<handle>/badge/agenda/agenda.json (then we cache + use that).
# (start_min, end_min|None, title, subtitle)
DEFAULT_DAYS = (
    ("OCT 27 - DAY 0", (10, 27), (
        (480, 1020, "Invite-only programming", "On the list? We'll reach out"),
    )),
    ("OCT 28 - DAY 1", (10, 28), (
        (450, None, "Doors open", "Fort Mason Center"),
        (540, None, "Keynote", ""),
        (600, 1050, "Breakout sessions", "All experiences open"),
        (1080, None, "Evening events", "GitHub & partners"),
    )),
    ("OCT 29 - DAY 2", (10, 29), (
        (480, None, "Doors open", "Fort Mason Center"),
        (540, 840, "Breakout sessions", "All experiences open"),
        (840, None, "Closing keynote", ""),
        (900, None, "Campus closes", "See you next year!"),
    )),
    ("OCT 30 - DAY 3", (10, 30), (
        (480, 960, "Day of Learning", "GitHub HQ (extra ticket)"),
    )),
)


# ---- dynamic agenda: load the user's synced schedule, else the default ----
def _pmin(v):
    # accept "HH:MM" strings, plain minute ints, or None (open-ended session)
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    try:
        h, m = str(v).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def build_days(data):
    # JSON -> internal DAYS tuple. Friendly schema the user hand-edits:
    #   {"event": "...", "year": 2026, "days": [
    #     {"title": "OCT 28 - DAY 1", "date": "2026-10-28", "sessions": [
    #       {"start": "07:30", "end": null, "title": "...", "subtitle": "..."}]}]}
    days = []
    for d in data.get("days", []):
        date = d.get("date")
        md = (0, 0)
        if isinstance(date, (list, tuple)) and len(date) >= 2:
            md = (int(date[0]), int(date[1]))
        elif isinstance(date, str) and "-" in date:
            p = date.split("-")            # YYYY-MM-DD
            md = (int(p[1]), int(p[2]))
        sess = tuple(
            (_pmin(s.get("start", 0)), _pmin(s.get("end")),
             s.get("title", ""), s.get("subtitle", ""))
            for s in d.get("sessions", []))
        days.append((d.get("title", ""), md, sess))
    if not days:
        raise ValueError("no days")
    return tuple(days), int(data.get("year", DEFAULT_YEAR))


def load_cached():
    global DAYS, EVENT_YEAR, AGENDA_SRC
    try:
        DAYS, EVENT_YEAR = build_days(json.load(open(CACHE)))
        AGENDA_SRC = "github"
    except Exception:
        DAYS, EVENT_YEAR, AGENDA_SRC = DEFAULT_DAYS, DEFAULT_YEAR, "default"


def save_cache(data):
    try:
        fsutil.write_json(CACHE, data)     # atomic temp+rename
    except Exception as e:  # noqa: BLE001
        print("agenda cache write err", e)


DAYS = DEFAULT_DAYS
EVENT_YEAR = DEFAULT_YEAR
AGENDA_SRC = "default"
load_cached()


def _lt():
    return time.localtime()


def fmt_t(mins):
    h = mins // 60
    m = mins % 60
    if H24:
        return "%02d:%02d" % (h, m)
    ap = "AM" if h < 12 else "PM"
    return "%d:%02d %s" % (h % 12 or 12, m, ap)


def fmt_range(s, e):
    return fmt_t(s) + ((" - " + fmt_t(e)) if e is not None else "")


def today_index():
    t = _lt()
    if t[0] != EVENT_YEAR:
        return -1
    for i, d in enumerate(DAYS):
        if (t[1], t[2]) == d[1]:
            return i
    return -1


def session_state(day_i, sess):
    # 0 past, 1 live, 2 upcoming-today, 3 other-day
    if day_i != today_index():
        return 3
    t = _lt()
    nowmin = t[3] * 60 + t[4]
    st, en = sess[0], sess[1]
    end = en if en is not None else st + 45
    if nowmin >= end:
        return 0
    if st <= nowmin < end:
        return 1
    return 2


def banner():
    # returns (kind, text): live status driven by the synced clock
    ti = today_index()
    if ti >= 0:
        t = _lt()
        nowmin = t[3] * 60 + t[4]
        for s in DAYS[ti][2]:
            end = s[1] if s[1] is not None else s[0] + 45
            if s[0] <= nowmin < end:
                return ("now", s[2])
        for s in DAYS[ti][2]:
            if s[0] > nowmin:
                return ("next", "%s  %s" % (fmt_t(s[0]), s[2]))
        return ("next", "That's a wrap for today")
    try:
        t = _lt()
        today0 = time.mktime((t[0], t[1], t[2], 0, 0, 0, 0, 0))
        first = time.mktime((EVENT_YEAR, 10, 27, 0, 0, 0, 0, 0))
        after = time.mktime((EVENT_YEAR, 10, 31, 0, 0, 0, 0, 0))
        now = time.mktime(t)
        if now < first:
            days = int((first - today0) // 86400)
            return ("count", "Starts in %d day%s" % (days, "" if days == 1 else "s"))
        if now >= after:
            return ("done", "See you next year!")
    except Exception:
        pass
    return ("idle", "GitHub Universe '26")


# ---- layout: header (0-13) + day tab (15-30) + list; footer eats bottom 13 ----
LIST_TOP = 32
LIST_BOT = 118          # no footer: list runs to a small bottom margin
FOOT_Y = 105            # footer bar top (when shown); taller bar = more bottom breathing room
GAP = 7                 # gap between sessions


def _start_day():
    ti = today_index()
    if ti >= 0:
        return ti
    try:
        if time.mktime(_lt()) < time.mktime((EVENT_YEAR, 10, 27, 0, 0, 0, 0, 0)):
            return 0
    except Exception:
        pass
    return len(DAYS) - 1


day_i = _start_day()
scroll = 0
view = "list"          # "list" | "help" (shown when no badge repo/agenda yet)
toast = None           # transient status line in the footer
toast_at = 0


def _wrap(text, font, w):
    out, cur = [], ""
    for word in text.split(" "):
        t = word if not cur else cur + " " + word
        if _w(t, font) <= w:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out or [""]


# line advances INCLUDE leading so rows don't touch (glyph h + breathing room):
LH_TITLE = 11        # corpsavage h8 + 3px leading
LH_SMALL = 11        # corpsavage h8 + 3px leading


def _kh(kind):
    # per-line advance by kind: title uses the body font, time/subtitle the small one
    return LH_TITLE if kind == "h" else LH_SMALL


def _session_lines(s):
    # ("t" time / "h" title / "s" subtitle); title wraps in BODY (ALL CAPS), subtitle in SMALL
    lines = [("t", fmt_range(s[0], s[1]))]
    for ln in _wrap(s[2].upper(), BODY, 146):
        lines.append(("h", ln))
    if s[3]:
        for ln in _wrap(s[3], SMALL, 148):
            lines.append(("s", ln))
    return lines


def _lines_h(lines):
    return sum(_kh(k) for k, _ in lines)


def _day_height(di):
    return sum(_lines_h(_session_lines(s)) + GAP for s in DAYS[di][2])


def draw_syncing():
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 13))
    _t("agenda/", 4, 3, SMALL, WHITE)
    msg = "Syncing..."
    _t(msg, 80 - _w(msg, BODY) / 2, 48, BODY, LAV)
    sub = ghbadge.handle() + "/badge"
    _t(sub, 80 - _w(sub, SMALL) / 2, 68, SMALL, GRAY)


_help_qr = None


def _qr_for(text, box=72):
    # build a scannable QR sized to ~box px (same recipe as the Setup app)
    import qrcode
    q = qrcode.QRCode()
    q.set_text(text)
    size = q.get_size()[0]
    scale = max(1, box // (size + 2))
    pad = scale
    img = image(size * scale + pad * 2, size * scale + pad * 2)
    img.pen = color.rgb(255, 255, 255)
    img.rectangle(0, 0, img.width, img.height)
    img.pen = color.rgb(0, 0, 0)
    for yy in range(size):
        for xx in range(size):
            if q.get_module(xx, yy):
                img.rectangle(pad + xx * scale, pad + yy * scale, scale, scale)
    return img


def draw_help():
    global _help_qr
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 13))
    _t("agenda/", 4, 3, SMALL, WHITE)

    if not ghbadge.handle():
        # no profile yet -> they must link GitHub in Setup first (no repo to scan)
        _t("No GitHub username", 8, 24, SMALL, WHITE)
        _t("Open the Setup app to", 8, 44, SMALL, GRAY)
        _t("link your GitHub, then", 8, 55, SMALL, GRAY)
        _t("press B here to sync.", 8, 66, SMALL, GRAY)
        return

    # username set but no badge repo yet -> one-tap "Use this template" QR
    if _help_qr is None:
        try:
            _help_qr = _qr_for(ghbadge.template_generate_url())
        except Exception as e:  # noqa: BLE001
            print("qr err", e)
            _help_qr = False
    if _help_qr:
        screen.blit(_help_qr, vec2(6, 22))
        rx = 6 + _help_qr.width + 8
    else:
        rx = 8
    _t("Scan to", rx, 26, SMALL, WHITE)
    _t("make your", rx, 37, SMALL, WHITE)
    _t("badge repo", rx, 52, SMALL, LAV)
    _t("on GitHub", rx, 63, SMALL, GRAY)
    _t("Name it 'badge', then B", 8, 104, SMALL, LIME)


def _trigger_sync():
    # reboot-safe: paint the syncing screen, push it ONCE, then block on Wi-Fi
    # + HTTP inside this one frame so display.update() can't fire mid-association
    global view, toast, toast_at, DAYS, EVENT_YEAR, AGENDA_SRC, day_i, scroll
    draw_syncing()
    display.update()
    status, data = ghbadge.fetch_json("agenda/agenda.json")
    if status == "ok":
        # parse into LOCALS first so a bad payload can't half-assign the globals
        try:
            days, year = build_days(data)
        except Exception:
            toast = "agenda.json format error"
            view = "list"
        else:
            DAYS, EVENT_YEAR, AGENDA_SRC = days, year, "github"
            save_cache(data)        # write errors are swallowed inside; never a "format" error
            day_i = _start_day()
            scroll = 0
            toast = "Synced - " + ghbadge.repo_web()
            view = "list"
    elif status == "not_found":
        view = "help"
        toast = None
    elif status == "no_wifi":
        toast = "No Wi-Fi set up"
        view = "list"
    elif status == "rate_limited":
        toast = "GitHub busy - try B again"
        view = "list"
    else:
        toast = "Sync failed"
        view = "list"
    toast_at = badge.ticks
    return None


def update():
    global day_i, scroll, view, toast, toast_at
    if view == "help":
        draw_help()
        if badge.pressed(BUTTON_B):
            return _trigger_sync()
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_C):
            view = "list"
        return None
    # A+C held together = refresh, mirroring the badge app's force-refresh gesture
    if badge.held(BUTTON_A) and badge.held(BUTTON_C):
        return _trigger_sync()
    if badge.pressed(BUTTON_B):
        return _trigger_sync()
    if badge.pressed(BUTTON_A):
        day_i = (day_i - 1) % len(DAYS)
        scroll = 0
    if badge.pressed(BUTTON_C):
        day_i = (day_i + 1) % len(DAYS)
        scroll = 0

    # the footer (countdown / sync toast / first-run hint) eats the bottom strip,
    # so the list area shrinks then and busy days become scrollable, not clipped
    kind, btext = banner()
    foot = kind in ("count", "done", "idle")
    foot_text, foot_pen = btext, (LIME if kind == "count" else GRAY)
    if toast is not None and badge.ticks - toast_at < 3000:
        foot, foot_text, foot_pen = True, toast, LIME
    elif AGENDA_SRC == "default":
        # surface the sync gesture; if a countdown is also up, alternate (~3s each)
        if not foot or (badge.ticks // 3000) % 2 == 0:
            foot, foot_text, foot_pen = True, "Hold A+C to sync", LIME
    list_bot = (FOOT_Y - 2) if foot else LIST_BOT
    maxs = max(0, _day_height(day_i) - (list_bot - LIST_TOP))
    if badge.pressed(BUTTON_DOWN):
        scroll = min(maxs, scroll + 14)
    if badge.pressed(BUTTON_UP):
        scroll = max(0, scroll - 14)

    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))

    # one day's sessions, wrapped (drawn first; header/nav painted over the top)
    y = LIST_TOP - scroll
    for s in DAYS[day_i][2]:
        lines = _session_lines(s)
        h = _lines_h(lines) + GAP
        if y + h > LIST_TOP - 2 and y < list_bot:
            st = session_state(day_i, s)
            if st == 1:                              # happening now
                screen.pen = GREENDK
                screen.shape(shape.rounded_rectangle(2, y - 2, 156, _lines_h(lines) + 3, 3))
                screen.pen = GREEN
                screen.shape(shape.rectangle(2, y - 2, 2, _lines_h(lines) + 3))
            ly = y
            for knd, txt in lines:
                if knd == "t":
                    _t(txt, 9, ly, SMALL,
                       GRAY if st == 0 else (GREEN if st == 1 else LAV))
                    if st == 1:
                        _t("NOW", 152 - _w("NOW", SMALL), ly, SMALL, GREEN)
                elif knd == "h":
                    _t(txt, 9, ly, BODY, GRAY if st == 0 else WHITE)
                else:
                    _t(txt, 9, ly, SMALL, GRAY)
                ly += _kh(knd)
        y += h

    # mask the list above the header, then header + day tab
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, LIST_TOP - 1))
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 13))
    _t("agenda/", 4, 3, SMALL, WHITE)   # corpsavage 8px: fits the bar, no descender bleed
    t = _lt()
    clk = fmt_t(t[3] * 60 + t[4])
    _t(clk, 156 - _w(clk, SMALL), 3, SMALL, GRAY)

    # day tab:  A      DAY TITLE      C
    screen.pen = PANEL
    screen.shape(shape.rounded_rectangle(2, 15, 156, 15, 3))
    _t("A", 8, 19, SMALL, LAV)
    _t("C", 150, 19, SMALL, LAV)
    title = DAYS[day_i][0]
    _t(title, 80 - _w(title, SMALL) / 2, 19, SMALL, WHITE)

    # footer: countdown, transient sync toast, or the first-run "B sync" hint
    if foot:
        screen.pen = PANEL
        screen.shape(shape.rectangle(0, FOOT_Y, 160, 120 - FOOT_Y))
        ftxt = foot_text
        _t_track(ftxt, 80 - _w_track(ftxt, FOOT, FOOT_TRACK) / 2,
                 FOOT_Y + 3, FOOT, foot_pen, FOOT_TRACK)

    # scrollbar when a day overflows the (footer-adjusted) list area
    if maxs > 0:
        track = list_bot - LIST_TOP
        bar = max(8, int(track * track / _day_height(day_i)))
        bp = int((track - bar) * scroll / maxs)
        screen.pen = PANEL
        screen.shape(shape.rounded_rectangle(157, LIST_TOP, 2, track, 1))
        screen.pen = GRAY
        screen.shape(shape.rounded_rectangle(157, LIST_TOP + bp, 2, bar, 1))
    return None


run(update)
