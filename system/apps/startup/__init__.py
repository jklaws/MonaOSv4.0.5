# MonaOS 4.0.5 boot screen — animated system-initialization sequence.
# A developer-style POST log types out with [OK] checks, the GitHub Universe '26
# hero "renders in" behind a scan-wipe, then a segmented HUD loader counts to
# 100%. Runs once on cold boot; press any button to skip.
import sys
import os

sys.path.insert(0, "/system/apps/startup")
os.chdir("/system/apps/startup")

import badgeware  # noqa: F401

screen.antialias = X2
boot = image.load("/system/apps/startup/boot.png")

# ---- fonts -------------------------------------------------------------------
F_LOG = pixel_font.load("/system/assets/fonts/corpsavage6.ppf")   # 6px boot log
F_UI = pixel_font.load("/system/assets/fonts/corpsavage.ppf")     # 8px UI / HUD

# ---- palette -----------------------------------------------------------------
BG = color.rgb(6, 9, 14)
NEON = color.rgb(63, 185, 80)
DIMG = color.rgb(33, 92, 50)
CYAN = color.rgb(86, 180, 255)
WHITE = color.rgb(235, 245, 255)
DIM = color.rgb(96, 116, 136)
TRACK = color.rgb(22, 28, 38)

# ---- timeline (ms) -----------------------------------------------------------
LINE_STEP = 185          # gap between successive boot lines starting
OK_DELAY = 110           # delay after a line shows before its [OK] lands
REVEAL_AT = 1480         # hero scan-wipe begins
REVEAL_LEN = 520         # scan-wipe duration
LOAD_AT = 1900           # segmented loader begins
DURATION = 3350          # total before auto-enter

LINES = [
    "RP2350  @250MHZ",
    "MOUNT   /SYSTEM",
    "DISPLAY 320X240",
    "RADIO   CYW43",
    "CLOCK   RTC SYNC",
    "APPS    LOADED",
]
N = len(LINES)
SPIN = "|/-\\"

LOG_X = 10
OK_X = 116
LOG_Y0 = 22
LOG_DY = 9

BX, BY, BW, BH = 24, 103, 112, 6   # loader bar footprint
SEGS = 18

_start = badge.ticks


def _text(font, txt, x, y, pen):
    screen.font = font
    screen.pen = pen
    screen.text(txt, int(x), int(y))


def _scanlines(alpha):
    # faint CRT/console texture
    screen.pen = color.rgb(18, 28, 40, alpha)
    y = 0
    while y < 120:
        screen.shape(shape.rectangle(0, y, 160, 1))
        y += 4


def _corners(pen, inset=3, arm=9, th=2):
    screen.pen = pen
    a, b, t = inset, arm, th
    r = 160 - inset
    bm = 120 - inset
    # top-left
    screen.shape(shape.rectangle(a, a, b, t))
    screen.shape(shape.rectangle(a, a, t, b))
    # top-right
    screen.shape(shape.rectangle(r - b, a, b, t))
    screen.shape(shape.rectangle(r - t, a, t, b))
    # bottom-left
    screen.shape(shape.rectangle(a, bm - t, b, t))
    screen.shape(shape.rectangle(a, bm - b, t, b))
    # bottom-right
    screen.shape(shape.rectangle(r - b, bm - t, b, t))
    screen.shape(shape.rectangle(r - t, bm - b, t, b))


def update():
    t = badge.ticks - _start

    if badge.pressed():
        return True

    # ===================== background =====================
    screen.pen = BG
    screen.clear()

    pre = min(1.0, t / max(1, REVEAL_AT))
    if t < REVEAL_AT + REVEAL_LEN:
        _scanlines(int(70 * (1.0 - pre * 0.4)))

    # ===================== terminal POST log =====================
    if t < REVEAL_AT + REVEAL_LEN:
        # title + blinking cursor
        cur = "_" if ((t // 380) % 2 == 0) else " "
        _text(F_UI, "MonaOS", LOG_X, 8, WHITE)
        w = screen.measure_text("MonaOS")[0]
        _text(F_UI, "//boot " + cur, LOG_X + w + 4, 8, NEON)

        for i, label in enumerate(LINES):
            appear = i * LINE_STEP
            if t < appear:
                break
            y = LOG_Y0 + i * LOG_DY
            done = t >= appear + OK_DELAY
            # prompt caret
            _text(F_LOG, ">", LOG_X - 4, y, DIMG if done else NEON)
            _text(F_LOG, label, LOG_X + 4, y, DIM if done else WHITE)
            if done:
                _text(F_LOG, "[OK]", OK_X, y, NEON)
            else:
                sp = SPIN[(t // 80) % 4]
                _text(F_LOG, sp, OK_X + 4, y, CYAN)

    # ===================== hero scan-wipe reveal =====================
    if t >= REVEAL_AT:
        rp = min(1.0, (t - REVEAL_AT) / REVEAL_LEN)
        reveal_h = int(120 * rp)
        if reveal_h > 0:
            screen.clip = rect(0, 0, 160, reveal_h)
            screen.blit(boot, vec2(0, 0))
            screen.clip = rect(0, 0, 160, 120)
        if rp < 1.0:
            # bright leading scan edge
            screen.pen = CYAN
            screen.shape(shape.rectangle(0, reveal_h - 1, 160, 2))
            screen.pen = color.rgb(235, 245, 255, 120)
            screen.shape(shape.rectangle(0, reveal_h, 160, 1))

    # ===================== HUD + segmented loader =====================
    if t >= LOAD_AT:
        lp = min(1.0, (t - LOAD_AT) / (DURATION - LOAD_AT - 400))
        ready = lp >= 1.0
        fade = min(255, int(255 * (t - LOAD_AT) / 220))
        _corners(color.rgb(63, 185, 80, fade) if ready else color.rgb(86, 180, 255, fade))

        # bar track
        screen.pen = color.rgb(22, 28, 38, fade)
        screen.shape(shape.rounded_rectangle(BX - 2, BY - 2, BW + 4, BH + 4, 2))

        seg_w = (BW - (SEGS - 1)) / SEGS
        lit = lp * SEGS
        for s in range(SEGS):
            x = BX + s * (seg_w + 1)
            if s < int(lit):
                screen.pen = color.rgb(63, 185, 80, fade)        # filled
            elif s < lit:
                # leading segment pulses
                g = int(120 + 100 * (lit - int(lit)))
                screen.pen = color.rgb(120, 245, 150, min(fade, g))
            else:
                screen.pen = color.rgb(30, 40, 52, fade)         # empty
            screen.shape(shape.rectangle(int(x), BY, max(2, int(seg_w)), BH))

        # percentage + status, above the bar
        pct = int(lp * 100)
        _text(F_UI, "%d%%" % pct, BX, BY - 13, WHITE)
        label = "READY" if ready else "INITIALIZING"
        lw = screen.measure_text(label)[0]
        _text(F_UI, label, BX + BW - lw, BY - 13, NEON if ready else CYAN)

    # rear case lights ramp with the boot
    badge.caselights(min(1.0, t / DURATION) * 0.5)

    if t >= DURATION:
        return True
    return None


run(update)
badge.caselights(0)
