import sys
import os

sys.path.insert(0, "/system/apps/mona_noir")
sys.path.insert(0, "/")
os.chdir("/system/apps/mona_noir")

import json
import random
import gc
import time
import math
import badgeware  # noqa: F401  builtins: screen, color, shape, image, badge, run, BUTTON_*, vec2, rect, pixel_font, X2
screen.antialias = X2
from badgeware import State

# ---------------------------------------------------------------------------
# MONA NOIR: Ghost in the Graph  (badge game, replaces Mona's Quest)
# Vertical slice: title -> map -> node -> crack mini-game -> reward -> collection.
# Offline + mock; GitHub/IR sync wired later. Procedural visuals for now.
# Controls: A/C = prev/next (or left/right in crack), UP/DOWN = up/collection /
# down/casefile (or up/down in crack), B = select/interact, HOME = exit.
# ---------------------------------------------------------------------------

F_BIG = pixel_font.load("/system/assets/fonts/absolute.ppf")
F_SM = pixel_font.load("/system/assets/fonts/ark.ppf")
F_TINY = pixel_font.load("/system/assets/fonts/corpsavage.ppf")

# Purple/indigo noir palette (matches the design sheet): near-black navy base,
# purple/violet Invertocat identity, green only for the Graph paths/restore,
# gold for score/rare, red/magenta for corruption/Nullcat.
BG = color.rgb(10, 9, 20)
PANEL = color.rgb(26, 22, 46)
G_DK = color.rgb(3, 58, 22)
G_MID = color.rgb(25, 108, 46)
G_HI = color.rgb(46, 160, 67)
G_LT = color.rgb(86, 211, 100)
WHITE = color.rgb(238, 240, 250)
MUTED = color.rgb(150, 140, 178)
RED = color.rgb(248, 81, 73)
MAGENTA = color.rgb(255, 106, 193)
GOLD = color.rgb(232, 176, 48)
LIME = color.rgb(211, 250, 55)
PURPLE = color.rgb(139, 92, 246)
VIOLET = color.rgb(178, 150, 255)
CYAN = color.rgb(120, 220, 240)


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print("data load err", path, e)
        return default


WORLD = _load("data/world.json", {"districts": []})
PINDB = _load("data/pins.json", {})
DISTRICTS = WORLD.get("districts", [])

PINS = {}
PIN_ORDER = []
for _grp in ("starter", "common", "rare", "defense", "ultra_rare", "bonus"):
    for _p in PINDB.get(_grp, []):
        PINS[_p["pin_id"]] = dict(_p, tier=_grp)
        PIN_ORDER.append(_p["pin_id"])

# tier -> pins that can drop (simplified pool)
DROP_POOL = {
    1: [p for p, m in PINS.items() if m["tier"] == "common"],
    2: [p for p, m in PINS.items() if m["tier"] in ("common", "rare")],
    3: [p for p, m in PINS.items() if m["tier"] in ("rare", "defense")],
    4: [p for p, m in PINS.items() if m["tier"] in ("rare", "defense", "ultra_rare")],
}

state = {"score": 0, "restored": [], "pins": [], "verified": False, "streak": 0}
State.load("mona_noir", state)

session = {"glitch_clears": 0}

# ---- IR beacon receiver: in-person cracking (NEC over PIO, addr 0x45) -------
# Coexists with the LCD (display is PIO1; the receiver is PIO0/SM0). No Wi-Fi,
# so no render/association reboot risk. Reuses the existing event beacons.
_ir_hit = [None]
_ir_rx = None
try:
    from aye_arr.nec import NECReceiver
    from aye_arr.nec.remotes.descriptor import RemoteDescriptor

    _BEACON_CODES = {}
    for _d in DISTRICTS:
        _bc = _d.get("beacon_code")
        if _bc:
            _BEACON_CODES[_d["level_id"]] = int(_bc, 16)

    class _Beacon(RemoteDescriptor):
        NAME = "GithubUniverseBeacon"
        ADDRESS = 0x45
        BUTTON_CODES = _BEACON_CODES

        def __init__(self):
            super().__init__()

    _bcn = _Beacon()
    _bcn.on_known = lambda lid: _ir_hit.__setitem__(0, lid)
    _ir_rx = NECReceiver(21, 0, 0)
    _ir_rx.bind(_bcn)
    _ir_rx.start()
except Exception as e:
    print("IR init skipped:", e)
    _ir_rx = None


def ir_poll():
    if _ir_rx is not None:
        for _ in range(4):           # drain the PIO buffer (a beacon burst can
            try:                     # span several frames; real beacons repeat)
                _ir_rx.decode()
            except Exception:
                break
    h = _ir_hit[0]
    _ir_hit[0] = None
    return h

view = "title"
sel = 0
result = {}
crack = None
coll_top = 0
coll_sel = 0
coll_hold_at = 0   # ms timestamp gating hold-to-scroll auto-repeat in the collection
daily_bonus = 0
daily_at = 0
sync_result = {}


def save():
    try:
        State.save("mona_noir", state)
    except Exception as e:
        print("save err", e)


def award_pin(pid):
    if pid and pid not in state["pins"]:
        state["pins"].append(pid)
        return True
    return False


_bg = None
_bg_name = None
_pin_cache = {}


def use_bg(name):
    # one background slot; loads on change, frees the old (memory-safe)
    global _bg, _bg_name
    if name != _bg_name:
        _bg = None
        gc.collect()
        if name:
            try:
                _bg = image.load("assets/%s.png" % name)
            except Exception:
                _bg = None
        _bg_name = name
    return _bg


def pin_img(pid):
    if pid not in _pin_cache:
        if len(_pin_cache) > 26:
            _pin_cache.clear()
        try:
            _pin_cache[pid] = image.load("assets/pin_%s.png" % pid)
        except Exception:
            _pin_cache[pid] = None
    return _pin_cache[pid]


def collection_ids():
    owned = state["pins"]
    return [p for p in PIN_ORDER if PINS[p]["tier"] != "bonus" or p in owned]


_char_cache = {}


def char_img(name):
    if name not in _char_cache:
        try:
            _char_cache[name] = image.load("assets/char_%s.png" % name)
        except Exception:
            _char_cache[name] = None
    return _char_cache[name]


_ui_cache = {}


def ui_img(name):
    if name not in _ui_cache:
        try:
            _ui_cache[name] = image.load("assets/ui_%s.png" % name)
        except Exception:
            _ui_cache[name] = None
    return _ui_cache[name]


_dist_cache = {}


def district_img(n):
    if n not in _dist_cache:
        try:
            _dist_cache[n] = image.load("assets/district_%d.png" % n)
        except Exception:
            _dist_cache[n] = None
    return _dist_cache[n]


_tile_cache = {}
_TILE_NAME = {"#": "path", "X": "corrupt", "L": "lock", "R": "root",
              "*": "bonus", "S": "start", ".": "empty"}


def tile_img(ch):
    name = _TILE_NAME.get(ch)
    if not name:
        return None
    if name not in _tile_cache:
        try:
            _tile_cache[name] = image.load("assets/tile_%s.png" % name)
        except Exception:
            _tile_cache[name] = None
    return _tile_cache[name]


# ---- meta systems: daily streak, pin sets, completion -----------------------
def today_key():
    try:
        t = time.localtime()
        return t[0] * 1000 + t[7]   # year*1000 + day-of-year
    except Exception:
        return 0


def check_daily():
    dk = today_key()
    if not dk:
        return 0
    last = state.get("last_day")
    if dk != last:
        state["streak"] = state.get("streak", 0) + 1 if (last and dk == last + 1) else 1
        state["last_day"] = dk
        bonus = 50 * state["streak"]
        state["score"] += bonus
        save()
        return bonus
    return 0


def check_sets():
    sets = PINDB.get("sets", {})
    done = state.setdefault("sets_done", [])
    newname = None
    for sid, sdef in sets.items():
        if sid not in done and all(p in state["pins"] for p in sdef.get("pins", [])):
            done.append(sid)
            state["score"] += 200
            newname = sdef.get("name", sid)
    return newname


def is_complete():
    if not all(d["level_id"] in state["restored"] for d in DISTRICTS):
        return False
    return all(p in state["pins"] for p in PIN_ORDER if PINS[p]["tier"] != "bonus")


def difficulty(tier):
    return {1: "ROOKIE", 2: "FIELD", 3: "DEEP", 4: "ROOT"}.get(tier, "FIELD")


def available(d):
    req = d.get("unlock_requirements", {})
    n = len(state["restored"])
    if "graph_restored_percent_min" in req:
        return n >= 9
    return n >= (d.get("order", 1) - 1)


# ---- procedural background: dark with a faint green contribution frame --------
def graph_frame():
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    screen.pen = color.rgb(14, 30, 20)
    for gx in range(0, 160, 8):
        for gy in range(0, 120, 8):
            edge = gx < 8 or gx > 150 or gy < 8 or gy > 110
            if edge:
                k = ((gx + gy) // 8) % 3
                screen.pen = G_DK if k == 0 else (color.rgb(46, 30, 78) if k == 1 else G_MID)
                screen.shape(shape.rectangle(gx + 1, gy + 1, 6, 6))


def header(title, right=""):
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 12))
    screen.font = F_TINY
    screen.pen = G_LT
    screen.text(title, 4, 3)
    if right:
        screen.pen = MUTED
        w, _ = screen.measure_text(right)
        screen.text(right, 156 - w, 3)


def button_bar(a=None, b=None, c=None):
    # bottom prompt bar. The gold A/B/C letter sits directly OVER its physical
    # button (anchoring the whole label would mis-place the letter, since the
    # action words differ in width). Measured straight-on from the device: the
    # pressable button centers are at screen-x ~17 / ~68 / ~117. The action word
    # trails to the right of its letter. UP/DOWN live on the right edge.
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 108, 160, 12))
    screen.font = F_TINY
    for label, cx in ((a, 19), (b, 70), (c, 119)):
        if not label:
            continue
        letter = label[0]                        # "A:crack" -> "A"
        action = label[2:]                        #            -> "crack"
        lw, _ = screen.measure_text(letter)
        x = int(cx - lw / 2)                       # center the LETTER on the button
        if x < 2:
            x = 2
        screen.pen = GOLD
        screen.text(letter, x, 110)               # the button letter, over the button
        screen.pen = MUTED
        screen.text(action, x + lw + 2, 110)      # the action, trailing right


# ---------------------------------------------------------------- TITLE --------
def draw_title():
    bg = use_bg("bg_title")       # the top-left hero poster from the sheet
    if bg:
        screen.blit(bg, vec2(0, 0))
        if is_complete():
            screen.font = F_TINY
            screen.pen = LIME
            c = "* ROOT KEY HOLDER *"
            w, _ = screen.measure_text(c)
            screen.text(c, int(80 - w / 2), 2)
        # blinking CTA in a dark pill (the hero art has no "press" prompt)
        if (badge.ticks // 500) % 2 == 0:
            screen.font = F_TINY
            p = "PRESS A"
            w, _ = screen.measure_text(p)
            screen.pen = color.rgb(8, 7, 16)
            screen.shape(shape.rounded_rectangle(int(80 - w / 2) - 7, 104, w + 14, 14, 6))
            screen.pen = LIME
            screen.text(p, int(80 - w / 2), 107)
        return
    # fallback (art missing): draw the title procedurally
    graph_frame()
    ci = char_img("invertocat")
    if ci:
        screen.blit(ci, vec2(118, 70))
    screen.font = F_BIG
    screen.pen = WHITE
    t = "MONA NOIR"
    w, _ = screen.measure_text(t)
    screen.text(t, int(80 - w / 2), 22)
    screen.font = F_SM
    screen.pen = VIOLET
    s = "Ghost in the Graph"
    w, _ = screen.measure_text(s)
    screen.text(s, int(80 - w / 2), 42)
    screen.font = F_TINY
    screen.pen = G_LT
    tag = "RESTORE . CRACK . CONNECT"
    w, _ = screen.measure_text(tag)
    screen.text(tag, int(80 - w / 2), 58)
    if is_complete():
        screen.pen = LIME
        c = "* ROOT KEY HOLDER *"
        w, _ = screen.measure_text(c)
        screen.text(c, int(80 - w / 2), 74)
    screen.font = F_SM
    screen.pen = WHITE
    p = "Press A"
    w, _ = screen.measure_text(p)
    if (badge.ticks // 500) % 2 == 0:
        screen.text(p, int(80 - w / 2), 92)


# --------------------------------------------------------------- INTRO ---------
INTRO_LINES = [
    ("NULLCAT corrupted the", MAGENTA),
    ("Graph & stole the", WHITE),
    ("Invertocat.", VIOLET),
    ("", WHITE),
    ("You're MONA NOIR: crack", WHITE),
    ("the 9 district nodes,", G_LT),
    ("collect pins, restore", G_LT),
    ("the Graph to free it.", G_LT),
]


def draw_intro():
    graph_frame()
    header("THE CASE")
    screen.font = F_TINY
    y = 17
    for t, c in INTRO_LINES:
        if t:
            screen.pen = c
            screen.text(t, 10, y)            # inset past the x1-6 graph border
        y += 11
    button_bar(a="A:begin", b="B:back")


# ----------------------------------------------------------------- MAP ---------
MAP_COLS = 5
NODE_W = 28
NODE_H = 30


def draw_map():
    graph_frame()
    header("THE GRAPH", "%d/%d" % (len(state["restored"]), len(DISTRICTS)))
    ox, oy = 9, 16
    for i, d in enumerate(DISTRICTS):
        cx = ox + (i % MAP_COLS) * NODE_W
        cy = oy + (i // MAP_COLS) * NODE_H
        done = d["level_id"] in state["restored"]
        avail = available(d)
        if done:
            screen.pen = G_HI
        elif avail:
            pulse = (badge.ticks // 350) % 2 == 0
            screen.pen = G_MID if pulse else G_DK
        else:
            screen.pen = color.rgb(30, 36, 44)
        screen.shape(shape.rounded_rectangle(cx, cy, 24, 22, 4))
        screen.font = F_SM
        screen.pen = WHITE if (done or avail) else MUTED
        lbl = str(d.get("order", i + 1))
        w, _ = screen.measure_text(lbl)
        screen.text(lbl, int(cx + 12 - w / 2), cy + 4)
        if i == sel:
            screen.pen = LIME
            screen.shape(shape.rounded_rectangle(cx - 2, cy - 2, 28, 26, 5))
            screen.pen = G_DK if not done else G_HI
            screen.shape(shape.rounded_rectangle(cx, cy, 24, 22, 4))
            screen.font = F_SM
            screen.pen = WHITE
            screen.text(lbl, int(cx + 12 - w / 2), cy + 4)
        # state glyph (color-not-only): check = restored, lock = locked
        gim = ui_img("check") if done else (None if avail else ui_img("lock"))
        if gim:
            screen.blit(gim, rect(cx + 14, cy + 1, 9, 9))
    # bottom info: selected node name + status, then the button bar.
    # Inset past the x1-7 graph border (and short of the right border at x153);
    # drop to the tiny font for any name too wide for the F_SM slot.
    d = DISTRICTS[sel]
    INX = 10
    nm = d["display_name"]
    screen.font = F_SM
    if screen.measure_text(nm)[0] > 138:
        screen.font = F_TINY
    screen.pen = VIOLET
    screen.text(nm, INX, 70)
    screen.font = F_TINY
    st = "RESTORED" if d["level_id"] in state["restored"] else ("OPEN" if available(d) else "LOCKED")
    screen.pen = G_HI if st == "RESTORED" else (G_LT if st == "OPEN" else MUTED)
    screen.text("%s  tier %d" % (st, d.get("tier", 1)), INX, 86)
    button_bar(a="A:crack", b="B:case", c="C:pins")
    # daily-streak toast
    if daily_bonus and (badge.ticks - daily_at) < 2800:
        screen.pen = color.rgb(20, 60, 38)
        screen.shape(shape.rounded_rectangle(20, 38, 120, 28, 6))
        screen.pen = LIME
        screen.font = F_TINY
        m = "DAY STREAK x%d" % state.get("streak", 1)
        w, _ = screen.measure_text(m)
        screen.text(m, int(80 - w / 2), 43)
        screen.pen = WHITE
        m2 = "+%d pts" % daily_bonus
        w, _ = screen.measure_text(m2)
        screen.text(m2, int(80 - w / 2), 54)


def draw_node():
    graph_frame()
    d = DISTRICTS[sel]
    done = d["level_id"] in state["restored"]
    avail = available(d)
    header("NODE", "tier %d" % d.get("tier", 1))
    di = district_img(d.get("order", sel + 1))
    if di:
        screen.blit(di, rect(8, 18, 40, 40))
    else:
        screen.pen = PANEL
        screen.shape(shape.rounded_rectangle(8, 18, 40, 40, 5))
    nm = d["display_name"]
    # name: word-wrap into up to two lines so long names don't run off x156
    screen.font = F_SM
    screen.pen = VIOLET
    if screen.measure_text(nm)[0] <= 100:
        screen.text(nm, 54, 20)
    else:
        line = ""
        ny = 18
        for word in nm.split(" "):
            t = (line + " " + word).strip()
            if line and screen.measure_text(t)[0] > 100:
                screen.text(line, 54, ny)
                ny += 11
                line = word
            else:
                line = t
        if line:
            screen.text(line, 54, ny)
    screen.font = F_TINY
    # difficulty stars (short label keeps clear of the stars at x112)
    screen.pen = MUTED
    screen.text("diff", 54, 40)
    for i in range(4):
        screen.pen = GOLD if i < d.get("tier", 1) else color.rgb(60, 55, 80)
        screen.shape(shape.rounded_rectangle(112 + i * 11, 40, 8, 7, 1))
    # status (gap between label and value; longest value RESTORED ends at x148)
    screen.pen = MUTED
    screen.text("state", 54, 52)
    screen.pen = G_HI if done else (G_LT if avail else RED)
    screen.text("RESTORED" if done else ("OPEN" if avail else "LOCKED"), 96, 52)
    # access + flavor line
    screen.pen = MUTED
    screen.text("Access via IR or Wi-Fi", 8, 66)
    glitched = (hash(d["level_id"]) + badge.ticks // 60000) % 3 == 0
    if glitched:
        screen.pen = MAGENTA
        screen.text("GLITCHED! bonus drops", 8, 80)
    elif done:
        screen.pen = G_HI
        screen.text("Restored - replay it", 8, 80)
    elif not avail:
        screen.pen = MUTED
        screen.text("Restore earlier nodes", 8, 80)
    else:
        screen.pen = VIOLET
        screen.text("Trace the path. Crack it.", 8, 80)
    if avail:
        button_bar(a="A:crack", b="B:back")
    else:
        button_bar(b="B:back")


# --------------------------------------------------------------- CRACK ---------
def start_crack(d, src="local"):
    global crack, view
    random.seed((hash(d["level_id"]) & 0x7fffffff) ^ (len(state["restored"]) * 131))
    tier = d.get("tier", 1)
    GW, GH = 11, 7
    grid = [["#"] * GW for _ in range(GH)]
    for x in range(GW):
        grid[0][x] = "."
        grid[GH - 1][x] = "."
    for y in range(GH):
        grid[y][0] = "."
        grid[y][GW - 1] = "."
    start = (1, GH - 2)
    root = (GW - 2, 1)
    spine = set()
    for y in range(1, GH - 1):
        spine.add((1, y))
    for x in range(1, GW - 1):
        spine.add((x, 1))
    ncorr = {1: 5, 2: 9, 3: 14, 4: 18}.get(tier, 8)
    placed = 0
    tries = 0
    while placed < ncorr and tries < 600:
        tries += 1
        x = random.randint(1, GW - 2)
        y = random.randint(1, GH - 2)
        if (x, y) in spine or (x, y) == start or (x, y) == root or grid[y][x] != "#":
            continue
        grid[y][x] = "X"
        placed += 1
    nlock = {1: 0, 2: 1, 3: 2, 4: 2}.get(tier, 1)
    spc = [c for c in spine if c not in (start, root)]
    for i in range(len(spc) - 1, 0, -1):       # Fisher-Yates (MicroPython random has no shuffle)
        j = random.randint(0, i)
        spc[i], spc[j] = spc[j], spc[i]
    for i in range(min(nlock, len(spc))):
        x, y = spc[i]
        grid[y][x] = "L"
    for _ in range({1: 1, 2: 2, 3: 3, 4: 3}.get(tier, 1)):
        for _t in range(25):
            x = random.randint(1, GW - 2)
            y = random.randint(1, GH - 2)
            if grid[y][x] == "#" and (x, y) not in spine:
                grid[y][x] = "*"
                break
    grid[start[1]][start[0]] = "S"
    grid[root[1]][root[0]] = "R"
    secs = {1: 40, 2: 34, 3: 28, 4: 26}.get(tier, 35)
    glitched = (hash(d["level_id"]) + badge.ticks // 60000) % 3 == 0
    crack = {"grid": grid, "GW": GW, "GH": GH, "px": start[0], "py": start[1],
             "root": root, "t_end": badge.ticks + secs * 1000, "t_total": secs * 1000,
             "star_total": {1: 1, 2: 2, 3: 3, 4: 3}.get(tier, 1),
             "signal": 100, "mistakes": 0, "bonus": 0, "node": d, "glitched": glitched,
             "flash": 0, "src": src}
    view = "crack"


def crack_move(dx, dy):
    g = crack
    nx, ny = g["px"] + dx, g["py"] + dy
    if nx < 1 or nx > g["GW"] - 2 or ny < 1 or ny > g["GH"] - 2:
        return
    t = g["grid"][ny][nx]
    if t == ".":
        return
    if t == "X":
        g["mistakes"] += 1
        g["signal"] -= 30
        g["flash"] = badge.ticks
        if g["signal"] <= 0:
            finish_crack(False)
        return
    if t == "L":
        return  # must open with B
    if t == "*":
        g["bonus"] += 1
        g["grid"][ny][nx] = "#"
    g["px"], g["py"] = nx, ny
    if t == "R":
        finish_crack(True)


def crack_interact():
    g = crack
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x, y = g["px"] + dx, g["py"] + dy
        if 0 <= y < g["GH"] and 0 <= x < g["GW"] and g["grid"][y][x] == "L":
            g["grid"][y][x] = "#"


def finish_crack(won):
    global view, result
    g = crack
    tier = g["node"].get("tier", 1)
    if not won:
        result = {"won": False, "node": g["node"]}
        view = "result"
        return
    time_left = max(0, g["t_end"] - badge.ticks)          # ms remaining
    secs_left = time_left // 1000
    clean = g["mistakes"] == 0
    time_frac = (time_left / g["t_total"]) if g["t_total"] else 0.0
    star_total = g.get("star_total", 1) or 1
    star_frac = min(1.0, g["bonus"] / star_total)
    # SPEED-WEIGHTED score (time dominates) -> the number you replay to beat.
    score = (1000 * tier
             + secs_left * 40
             + g["signal"] * 8
             + g["bonus"] * 150
             + (600 if g["glitched"] else 0)
             - g["mistakes"] * 120)
    if score < 0:
        score = 0
    # grade from normalised quality (speed 50%, signal 30%, stars 20%, +clean bonus)
    quality = 0.50 * time_frac + 0.30 * (g["signal"] / 100.0) + 0.20 * star_frac
    if clean:
        quality += 0.06
    grade = ("S+" if quality >= 0.85 else "S" if quality >= 0.72
             else "A" if quality >= 0.55 else "B" if quality >= 0.38 else "C")
    top = grade in ("S", "S+")                              # high grade -> better drop tier
    state["score"] += score
    # per-node best score = the replay incentive ("beat your time")
    best = state.setdefault("best", {})
    lid = g["node"]["level_id"]
    new_best = score > best.get(lid, 0)
    if new_best:
        best[lid] = score
    newnode = g["node"]["level_id"] not in state["restored"]
    if newnode:
        state["restored"].append(g["node"]["level_id"])
    # pin drop -- a perfect crack OR a glitched node bumps the drop tier
    pool = DROP_POOL.get(tier, [])
    if (top or g["glitched"]) and DROP_POOL.get(min(4, tier + 1)):
        pool = DROP_POOL[min(4, tier + 1)]
    pct = len(state["restored"]) * 100 // max(1, len(DISTRICTS))
    if pct < 75:                      # ultra-rares are a late-game long-tail
        pool = [p for p in pool if PINS[p]["tier"] != "ultra_rare"]
    # prefer a pin you DON'T own yet, so cracking/re-cracking steadily fills the
    # collection. (Pure-random drops dup-ed out and left players stuck ~10/22.)
    pid = None
    if pool:
        fresh = [p for p in pool if p not in state["pins"]]
        chooser = fresh if fresh else pool
        pid = chooser[random.randint(0, len(chooser) - 1)]
    got = award_pin(pid)
    if got and pid:
        state.setdefault("prov", {})[pid] = g.get("src", "local")
    setname = check_sets() if got else None
    # duck bonus: clear 3 glitched nodes in one session
    duck = None
    if g["glitched"]:
        session["glitch_clears"] += 1
        if session["glitch_clears"] >= 3 and "rubber_ducky" not in state["pins"]:
            award_pin("rubber_ducky")
            duck = True
    save()
    result = {"won": True, "grade": grade, "score": score, "best": best[lid],
              "new_best": new_best, "secs_left": secs_left, "signal": g["signal"],
              "stars": g["bonus"], "glitched": g["glitched"],
              "pin": pid if got else None,
              "dup": pid if (pid and not got) else None, "node": g["node"],
              "duck": duck, "set": setname, "complete": is_complete()}
    view = "result"


def draw_crack():
    g = crack
    if badge.ticks > g["t_end"]:
        finish_crack(False)
        return
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    # top bar: timer + signal
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 0, 160, 12))
    tl = max(0, (g["t_end"] - badge.ticks) // 1000)
    screen.font = F_TINY
    screen.pen = WHITE if tl > 8 else RED
    screen.text("T %2ds" % tl, 4, 3)
    screen.pen = MAGENTA if g["glitched"] else MUTED
    nm = "! GLITCHED" if g["glitched"] else g["node"]["display_name"][:14]
    w, _ = screen.measure_text(nm)
    screen.text(nm, 156 - w, 3)
    # grid (rendered with the crack tileset)
    CS = 14
    ox = int(80 - g["GW"] * CS / 2)
    oy = 14
    flash_on = (badge.ticks - g["flash"]) < 120
    # playfield frame so the grid reads clearly against the dark background
    screen.pen = G_DK
    screen.shape(shape.stroke(shape.rectangle(ox - 2, oy - 2, g["GW"] * CS + 4, g["GH"] * CS + 4), 1))
    for y in range(g["GH"]):
        for x in range(g["GW"]):
            t = g["grid"][y][x]
            px, py = ox + x * CS, oy + y * CS
            im = tile_img(t)
            if im:
                screen.blit(im, vec2(px, py))
            elif t != ".":
                screen.pen = {"X": RED, "L": GOLD, "*": LIME, "R": G_LT, "S": G_MID}.get(t, G_DK)
                screen.shape(shape.rounded_rectangle(px + 1, py + 1, CS - 2, CS - 2, 2))
    # player cursor: a bright ring around the current cell (tile redrawn on top)
    px, py = ox + g["px"] * CS, oy + g["py"] * CS
    pulse = 1 + int(1.5 * (1 + math.sin(badge.ticks / 170.0)))   # ~1..4 px breathing ring
    screen.pen = RED if flash_on else WHITE
    screen.shape(shape.rounded_rectangle(px - pulse, py - pulse, CS + pulse * 2, CS + pulse * 2, 4))
    cim = tile_img(g["grid"][g["py"]][g["px"]])
    if cim:
        screen.blit(cim, vec2(px, py))
    else:
        screen.pen = G_MID
        screen.shape(shape.rounded_rectangle(px + 1, py + 1, CS - 2, CS - 2, 2))
    # signal bar (bottom, sheet-style)
    screen.pen = PANEL
    screen.shape(shape.rectangle(0, 112, 160, 8))
    screen.font = F_TINY
    screen.pen = G_LT
    screen.text("SIGNAL", 4, 112)
    bx, bw = 46, 86
    screen.pen = color.rgb(20, 40, 28)
    screen.shape(shape.rectangle(bx, 114, bw, 4))
    screen.pen = G_HI if g["signal"] > 30 else RED
    screen.shape(shape.rectangle(bx, 114, int(bw * max(0, g["signal"]) / 100), 4))
    screen.pen = MUTED
    screen.text("%d%%" % g["signal"], bx + bw + 3, 112)
    # corruption-hit feedback: brief full-screen red tint that fades out fast
    if flash_on:
        fa = 110 - (badge.ticks - g["flash"]) * 110 // 120
        if fa > 0:
            screen.pen = color.rgb(255, 40, 40, fa)
            screen.shape(shape.rectangle(0, 0, 160, 120))


# --------------------------------------------------------------- RESULT --------
def draw_result():
    r = result
    if not r.get("won"):
        screen.pen = color.rgb(40, 12, 12)
        screen.shape(shape.rectangle(0, 0, 160, 120))
        screen.font = F_BIG
        screen.pen = RED
        t = "TRACE LOST"
        w, _ = screen.measure_text(t)
        screen.text(t, int(80 - w / 2), 38)
        screen.font = F_TINY
        screen.pen = MUTED
        m = "Signal cut. Mona slips away."
        w, _ = screen.measure_text(m)
        screen.text(m, int(80 - w / 2), 64)
    else:
        graph_frame()
        # HERO grade letter, colour-coded so a glance reads the result
        gcol = {"S+": LIME, "S": LIME, "A": G_LT, "B": WHITE, "C": MUTED}.get(r["grade"], WHITE)
        screen.font = F_BIG
        screen.pen = gcol
        w, _ = screen.measure_text(r["grade"])
        screen.text(r["grade"], int(80 - w / 2), 1)
        # the WHY: time left / signal / stars (+GLITCH bonus marker)
        screen.font = F_TINY
        screen.pen = MUTED
        bd = "T%ds  SIG%d  *%d" % (r["secs_left"], r["signal"], r["stars"])
        if r.get("glitched"):
            bd += " +GLITCH"
        w, _ = screen.measure_text(bd)
        screen.text(bd, int(80 - w / 2), 17)
        # score + per-node best -> the replay hook ("beat your best")
        if r.get("new_best"):
            screen.pen = GOLD
            sc = "%d  NEW BEST!" % r["score"]
        else:
            screen.pen = WHITE
            sc = "%d pts   best %d" % (r["score"], r.get("best", r["score"]))
        w, _ = screen.measure_text(sc)
        screen.text(sc, int(80 - w / 2), 25)
        # big awarded pin, centered -- the label goes BELOW it (no overlap)
        pid = "rubber_ducky" if r.get("duck") else (r.get("pin") or r.get("dup"))
        im = pin_img(pid) if pid else None
        if im:
            screen.blit(im, rect(58, 34, 44, 44))
        elif pid:
            screen.pen = LIME if r.get("duck") else GOLD
            screen.shape(shape.rounded_rectangle(64, 36, 32, 32, 8))
        screen.font = F_SM
        if r.get("duck"):
            screen.pen = LIME
            m = "Rubber Ducky!"
        elif r.get("pin"):
            screen.pen = GOLD
            m = PINS.get(r["pin"], {}).get("name", r["pin"])
        elif r.get("dup"):
            screen.pen = MUTED
            m = "Duplicate"
        else:
            m = ""
        if m:
            w, _ = screen.measure_text(m)
            screen.text(m, int(80 - w / 2), 82)
        screen.font = F_TINY
        if r.get("set"):
            screen.pen = LIME
            m = "SET: " + r["set"]
        elif r.get("pin"):
            screen.pen = MUTED
            m = "NEW PIN"
        else:
            m = ""
        if m:
            w, _ = screen.measure_text(m)
            screen.text(m, int(80 - w / 2), 96)
    screen.font = F_TINY
    screen.pen = MUTED
    m = "Press A"
    w, _ = screen.measure_text(m)
    screen.text(m, int(80 - w / 2), 110)


# ------------------------------------------------------------- COLLECTION ------
_RIM = {"ultra_rare": LIME, "rare": GOLD, "defense": CYAN, "starter": WHITE,
        "bonus": LIME, "common": G_LT}


def _wrap(text, x, y, maxw, step, font):
    screen.font = font
    line = ""
    for word in text.split(" "):
        t = (line + " " + word).strip()
        if line and screen.measure_text(t)[0] > maxw:
            screen.text(line, x, y)
            y += step
            line = word
        else:
            line = t
    if line:
        screen.text(line, x, y)
        y += step
    return y


def draw_collection():
    # big-pin REVEAL carousel: one large pin at a time + name / tier / flavor
    graph_frame()
    ids = collection_ids()
    owned = state["pins"]
    nown = len([p for p in ids if p in owned])
    header("PINS", "%d/%d" % (nown, len(ids)))
    if not ids:
        return
    i = coll_sel % len(ids)
    pid = ids[i]
    m = PINS[pid]
    has = pid in owned
    rim = _RIM.get(m["tier"], G_MID) if has else color.rgb(50, 46, 72)
    # big framed pin (quality frame tinted by rarity), left side
    cx, cy = 42, 54
    screen.pen = rim
    screen.shape(shape.rounded_rectangle(cx - 28, cy - 28, 56, 56, 9))
    screen.pen = BG
    screen.shape(shape.rounded_rectangle(cx - 24, cy - 24, 48, 48, 7))
    if has:
        im = pin_img(pid)
        if im:
            screen.blit(im, rect(cx - 24, cy - 24, 48, 48))
        else:
            screen.pen = rim
            screen.shape(shape.rounded_rectangle(cx - 14, cy - 14, 28, 28, 6))
    else:
        screen.font = F_BIG
        screen.pen = MUTED
        w, _ = screen.measure_text("?")
        screen.text("?", int(cx - w / 2), cy - 13)
    # right column: name (wrapped), tier, flavor (wrapped)
    rx = 78
    screen.pen = (LIME if pid == "rubber_ducky" else rim) if has else MUTED
    y = _wrap(m["name"] if has else "Locked", rx, 18, 78, 13, F_SM)
    y += 2
    screen.font = F_TINY
    screen.pen = MUTED
    screen.text("SECRET" if m["tier"] == "bonus" else m["tier"].upper().replace("_", " "), rx, y)
    y += 12
    if has:
        screen.pen = WHITE
        _wrap(m.get("desc", ""), rx, y, 80, 10, F_TINY)
    else:
        screen.pen = MUTED
        screen.text("keep cracking", rx, y)
    # position + nav
    screen.font = F_TINY
    screen.pen = MUTED
    screen.text("%d / %d" % (i + 1, len(ids)), 14, 90)
    button_bar(a="A:prev", c="C:next", b="B:back")


def draw_detail():
    graph_frame()
    ids = collection_ids()
    pid = ids[coll_sel] if coll_sel < len(ids) else None
    header("PIN")
    if pid and pid in state["pins"]:
        im = pin_img(pid)
        if im:
            screen.blit(im, rect(16, 32, 56, 56))
        nm = PINS[pid]["name"]
        screen.pen = LIME if pid == "rubber_ducky" else GOLD
        if len(nm) <= 7:
            screen.font = F_BIG
            screen.text(nm, 80, 32)
            ny = 52
        else:
            screen.font = F_SM
            line = ""
            yy = 30
            for word in nm.split(" "):
                t = (line + " " + word).strip()
                if line and screen.measure_text(t)[0] > 78:
                    screen.text(line, 80, yy)
                    yy += 13
                    line = word
                else:
                    line = t
            if line:
                screen.text(line, 80, yy)
            ny = yy + 14
        screen.font = F_TINY
        screen.pen = G_LT
        screen.text(PINS[pid]["tier"].upper().replace("_", " "), 80, ny)
        ny += 11
        s = PINS[pid].get("set")
        if s:
            screen.pen = MUTED
            screen.text("set: " + s, 80, ny)
            ny += 11
        prov = state.get("prov", {}).get(pid)
        if prov:
            screen.pen = MUTED
            screen.text("trace: " + ("IR" if prov == "ir" else "remote"), 80, ny)
        if pid == "rubber_ducky":
            screen.pen = LIME
            screen.text("Secret bonus pin", 16, 96)
    button_bar(b="B:back")


def draw_casefile():
    graph_frame()
    header("CASE FILE")
    screen.font = F_SM
    screen.pen = WHITE
    screen.text("Score: %d" % state["score"], 8, 20)
    screen.text("Nodes: %d/%d" % (len(state["restored"]), len(DISTRICTS)), 8, 35)
    screen.text("Pins:  %d" % len(state["pins"]), 8, 50)
    pct = int(len(state["restored"]) / max(1, len(DISTRICTS)) * 100)
    screen.font = F_TINY
    screen.pen = G_LT
    screen.text("THE GRAPH: %d%% RESTORED" % pct, 8, 66)
    screen.pen = PANEL
    screen.shape(shape.rectangle(8, 76, 144, 8))
    screen.pen = G_HI
    screen.shape(shape.rectangle(8, 76, int(144 * pct / 100), 8))
    screen.font = F_TINY
    screen.pen = WHITE
    screen.text("Streak %d    Sets %d/%d" % (state.get("streak", 0),
                len(state.get("sets_done", [])), len(PINDB.get("sets", {}))), 8, 88)
    if is_complete():
        screen.pen = LIME
        c = "* ROOT KEY HOLDER *"
        w, _ = screen.measure_text(c)
        screen.text(c, int(80 - w / 2), 98)
    elif state.get("last_graph_pct") is not None:
        screen.pen = MUTED
        screen.text("World Graph %d%% (synced)" % state["last_graph_pct"], 8, 98)
    button_bar(b="B:back", c="C:sync")


def draw_syncing():
    graph_frame()
    header("SYNC")
    ci = char_img("invertocat")
    if ci:
        screen.blit(ci, vec2(64, 30))
    screen.font = F_SM
    screen.pen = G_LT
    m = "SYNCING..."
    w, _ = screen.measure_text(m)
    screen.text(m, int(80 - w / 2), 80)
    screen.font = F_TINY
    screen.pen = MUTED
    m = "uploading to the Graph"
    w, _ = screen.measure_text(m)
    screen.text(m, int(80 - w / 2), 96)


def draw_syncresult():
    graph_frame()
    header("SYNC")
    r = sync_result
    screen.font = F_SM
    ok = r.get("ok")
    screen.pen = G_LT if ok else RED
    t = "SYNCED" if ok else "OFFLINE"
    w, _ = screen.measure_text(t)
    screen.text(t, int(80 - w / 2), 16)
    screen.font = F_TINY
    y = 38
    if not r.get("wifi"):
        screen.pen = MUTED
        screen.text("No Wi-Fi. Open Settings.", 8, y)
        screen.text("Progress saved locally.", 8, y + 12)
    else:
        screen.pen = WHITE
        screen.text("Wi-Fi connected", 8, y)
        y += 12
        screen.pen = G_LT if r.get("pushed") else MUTED
        screen.text("Profile pushed" if r.get("pushed") else "Read-only (no token)", 8, y)
        y += 12
        if r.get("graph_pct") is not None:
            screen.pen = G_HI
            screen.text("World Graph: %d%%" % r["graph_pct"], 8, y)
            y += 12
        if r.get("rank"):
            screen.pen = GOLD
            screen.text("Your rank: #%d" % r["rank"], 8, y)
    button_bar(b="B:back")


# ---------------------------------------------------------------- LOOP ---------
def update():
    global view, sel, coll_top, coll_sel, coll_hold_at, daily_bonus, daily_at, sync_result
    if view == "title":
        draw_title()
        if badge.pressed(BUTTON_A):
            view = "intro"
    elif view == "intro":
        draw_intro()
        if badge.pressed(BUTTON_A):
            if not state["verified"]:
                state["verified"] = True
                award_pin("verified_profile")
                save()
            daily_bonus = check_daily()
            daily_at = badge.ticks
            use_bg(None)   # free any background
            view = "map"
        elif badge.pressed(BUTTON_B):
            view = "title"
    elif view == "map":
        draw_map()
        hit = ir_poll()                      # in-person IR beacon -> crack that node
        if hit:
            for i, d in enumerate(DISTRICTS):
                if d["level_id"] == hit:
                    sel = i
                    if available(d):
                        start_crack(d, "ir")
                    break
        if badge.pressed(BUTTON_UP):
            sel = (sel - 1) % len(DISTRICTS)
        elif badge.pressed(BUTTON_DOWN):
            sel = (sel + 1) % len(DISTRICTS)
        elif badge.pressed(BUTTON_A):
            view = "node"
        elif badge.pressed(BUTTON_C):
            coll_top = 0
            coll_sel = 0
            view = "collection"
        elif badge.pressed(BUTTON_B):
            view = "casefile"
    elif view == "node":
        draw_node()
        if badge.pressed(BUTTON_A) and available(DISTRICTS[sel]):
            start_crack(DISTRICTS[sel], "local")
        elif badge.pressed(BUTTON_B):
            view = "map"
    elif view == "crack":
        draw_crack()
        if crack is not None:
            if badge.pressed(BUTTON_UP):
                crack_move(0, -1)
            elif badge.pressed(BUTTON_DOWN):
                crack_move(0, 1)
            elif badge.pressed(BUTTON_A):
                crack_move(-1, 0)
            elif badge.pressed(BUTTON_C):
                crack_move(1, 0)
            elif badge.pressed(BUTTON_B):
                crack_interact()
    elif view == "result":
        draw_result()
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_B):
            view = "map"
    elif view == "collection":
        draw_collection()
        n = max(1, len(collection_ids()))
        # single-step on press; HOLD up/down (A/UP or C/DOWN) to auto-repeat for
        # fast browsing of a big pin collection (340ms initial delay, then 110ms).
        if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_UP):
            coll_sel = (coll_sel - 1) % n
            coll_hold_at = badge.ticks + 340
        elif badge.pressed(BUTTON_C) or badge.pressed(BUTTON_DOWN):
            coll_sel = (coll_sel + 1) % n
            coll_hold_at = badge.ticks + 340
        elif (badge.held(BUTTON_A) or badge.held(BUTTON_UP)) and badge.ticks >= coll_hold_at:
            coll_sel = (coll_sel - 1) % n
            coll_hold_at = badge.ticks + 110
        elif (badge.held(BUTTON_C) or badge.held(BUTTON_DOWN)) and badge.ticks >= coll_hold_at:
            coll_sel = (coll_sel + 1) % n
            coll_hold_at = badge.ticks + 110
        elif badge.pressed(BUTTON_B):
            view = "map"
    elif view == "casefile":
        draw_casefile()
        if badge.pressed(BUTTON_C):
            view = "syncing"
        elif badge.pressed(BUTTON_B) or badge.pressed(BUTTON_A):
            view = "map"
    elif view == "syncing":
        # reboot-safe: draw + push to the LCD ONCE, then run the blocking
        # Wi-Fi connect + GitHub sync. Because the network work happens inside
        # this one frame, the framework's per-frame display.update() (LCD DMA)
        # never overlaps the cyw43 association -> no render/association reboot.
        draw_syncing()
        display.update()
        try:
            import sync as _sync
            sync_result = _sync.sync(state)
        except Exception as e:
            sync_result = {"ok": False, "wifi": False, "msg": str(e)}
        if sync_result.get("graph_pct") is not None:
            state["last_graph_pct"] = sync_result["graph_pct"]
            save()
        view = "syncresult"
    elif view == "syncresult":
        draw_syncresult()
        if badge.pressed(BUTTON_B) or badge.pressed(BUTTON_A):
            view = "casefile"
    return None


run(update)
