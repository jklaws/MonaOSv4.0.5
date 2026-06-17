import sys
import os

sys.path.insert(0, "/system/apps/commitdash")
os.chdir("/system/apps/commitdash")

# v2.0.2: badgeware is a package that injects builtins
# (screen, color, shape, image, vec2, rect, pixel_font, badge, run, display,
#  BUTTON_A/B/C/UP/DOWN, OFF, X2).
import badgeware  # noqa: F401
from badgeware import State

# Fast shape game: AA OFF buys FPS (like flappy / bugbash auto-runners).
screen.antialias = OFF

import random
import math
import json

# Unified per-user badge repo + reboot-safe fetch (github.com/<handle>/badge),
# plus atomic, crash-safe cache writes — mirrors the agenda app's design so
# synced levels survive a reboot and the game stays fully playable offline.
ghbadge = __import__("/system/ghbadge")
fsutil = __import__("/system/fsutil")
LEVELS_CACHE = "/state/commitdash_levels.json"   # last synced levels, survives reboot

# ---------------------------------------------------------------------------
# COMMIT DASH  -  a Geometry-Dash-style auto-runner on the GitHub graph.
# World scrolls left at a constant speed; the cube holds a fixed x and jumps.
# Background = the GitHub contribution grid (scrolling + flickering). Obstacles
# are placeholder shapes: spikes (deadly) and blocks (land on / jump over).
# The level is data-driven via build_level(intensity_bins) so REAL GitHub
# contribution counts can plug in later (see build_level docstring).
# PLACEHOLDER ART: everything here is procedural shapes, no sprites yet.
# ---------------------------------------------------------------------------

F_BIG = pixel_font.load("/system/assets/fonts/absolute.ppf")
F_SM = pixel_font.load("/system/assets/fonts/ark.ppf")
F_TINY = pixel_font.load("/system/assets/fonts/corpsavage.ppf")

# --- sprites (small PNGs, blitted scaled-to-rect; ~7KB total decoded, loaded
#     once -> no per-frame decode, fine for the AA-OFF fast loop) -------------
_SPR = "/system/apps/commitdash/sprites/"
SP_RUN = image.load(_SPR + "player_run.png")     # grounded player
SP_AIR = image.load(_SPR + "player_air.png")     # airborne player (spin pose)
SP_SPIKE = image.load(_SPR + "spike.png")        # deadly spike
SP_BLOCK = image.load(_SPR + "block.png")        # land-on / jump-over block
SP_FIN = image.load(_SPR + "finish.png")         # finish portal at LEVEL_END
SP_BURST = image.load(_SPR + "burst.png")        # death explosion
SP_STAR = image.load(_SPR + "star.png")          # collectible repo-star
SP_SPARK = image.load(_SPR + "spark.png")        # collect burst
SP_BUG = image.load(_SPR + "bug.png")            # bug enemy (alt deadly obstacle)

# ---- palette (GitHub dark + the 4 contribution greens) --------------------
BG = color.rgb(13, 17, 23)
GH = (
    color.rgb(14, 68, 41),    # #0e4429  level 1
    color.rgb(0, 109, 50),    # #006d32  level 2
    color.rgb(38, 166, 65),   # #26a641  level 3
    color.rgb(57, 211, 83),   # #39d353  level 4
)
# dimmed/distant version of the palette for the BACKDROP grid. Depth trick: the
# contribution graph reads as far away (dark + slow parallax) so the foreground
# cube + obstacles stand out clearly.
GH_BG = (
    color.rgb(13, 33, 23),
    color.rgb(16, 46, 30),
    color.rgb(20, 62, 38),
    color.rgb(26, 84, 50),
)
GRID_EMPTY = color.rgb(18, 22, 28)        # empty contribution cell (dim)
PLAYER = color.rgb(57, 211, 83)           # bright-green cube
PLAYER_DK = color.rgb(13, 30, 19)         # cube eyes / outline
GROUND = color.rgb(38, 166, 65)
GROUND_DK = color.rgb(14, 68, 41)
SPIKE = color.rgb(57, 211, 83)
SPIKE_DK = color.rgb(8, 12, 18)
BLOCK = color.rgb(0, 109, 50)
BLOCK_HI = color.rgb(57, 211, 83)
WHITE = color.rgb(235, 242, 238)
MUTED = color.rgb(120, 138, 130)
RED = color.rgb(248, 81, 73)
GOLD = color.rgb(240, 196, 64)

# ---- world geometry --------------------------------------------------------
GROUND_Y = 104             # top of the ground strip (cube lands here)
PLAYER_X = 34              # fixed cube x
CUBE = 14                  # cube size (px)
SCROLL = 70.0             # world scroll speed (px / second)
GRAVITY = 620.0           # px / s^2
JUMP_V = -185.0           # base jump velocity
JUMP_V_HELD = -210.0      # slightly higher if A held at takeoff
SEG = 120                 # world px per level segment (one intensity bin)

GRID_TOP = 8               # contribution grid play-area top
GRID_BOTTOM = GROUND_Y - 2
CELL = 10                  # contribution cell size (incl. 1px gap)

# ---- persisted state -------------------------------------------------------
# best_by[level_name] = best % reached; last = last-played level name.
store = {"best_pct": 0, "best_dist": 0, "attempts": 0, "best_by": {}, "last": ""}
State.load("commitdash", store)
if "best_by" not in store:
    store["best_by"] = {}
if "last" not in store:
    store["last"] = ""
if "best_stars" not in store:
    store["best_stars"] = 0

# ---- the default level's bins (baked in -> fully playable offline) ---------
DEFAULT_BINS = [0, 1, 0, 2, 1, 3, 0, 2, 4, 1, 3, 2, 5, 1, 0, 2]

# Built-in levels, always available with zero setup / no Wi-Fi. Synced levels
# from the badge repo are MERGED on top of these (see load_levels()).
BUILTIN_LEVELS = [
    {"name": "Default", "bins": DEFAULT_BINS, "speed": SCROLL, "src": "builtin"},
    {"name": "Warm Up", "bins": [0, 0, 1, 0, 1, 0, 1, 0], "speed": 60.0, "src": "builtin"},
    {"name": "Crunch Week", "bins": [3, 4, 5, 4, 6, 5, 7, 4, 5, 6], "speed": 84.0, "src": "builtin"},
]


# ===========================================================================
# LEVEL MODEL  (the important hook for real GitHub data)
# ===========================================================================
def build_level(intensity_bins=None):
    """Build the obstacle layout from per-segment commit "intensity".

    intensity_bins : list[int] | None
        One int per level-segment = commit count for that slice of the run
        (the FUTURE: a user's real GitHub contribution counts, binned across
        the level). None -> a seeded, always-playable default layout.

    The structure encodes two rules so real data plugs straight in:

      1. BASELINE RHYTHM FLOOR -- every segment emits at least a minimum of
         jumpable obstacles, so a quiet / no-commit user (all zeros) still gets
         a real, completable level instead of an empty track.

      2. INTENSITY -> DENSITY / HEIGHT -- a busier segment (higher count) packs
         more obstacles and taller blocks. build_level([0,0,..]) is gentle;
         build_level([big,..]) is dense.

    Returns: list of obstacles, each a dict:
        {"t": "spike"|"block", "x": world_x, "w": width, "h": height}
    Plus the level length is stored on the returned list via .append of a
    sentinel handled by the caller; here we just return obstacles and let the
    caller derive the end from the last obstacle.
    """
    if intensity_bins is None:
        # Seeded default: a ~28s level. Gentle ramp of mixed intensity so the
        # prototype shows the full vocabulary (spikes, blocks, clusters).
        intensity_bins = DEFAULT_BINS
    # deterministic obstacle placement per bin-set so a given level always plays
    # the same (and synced levels are reproducible across reboots).
    random.seed(0xC0DE)

    # GAP_MIN = the closest two obstacles may sit and still be jumpable at the
    # current scroll speed (so every generated level stays completable). Busier
    # segments tighten toward GAP_MIN; quiet ones spread out to GAP_MAX.
    GAP_MIN = 40
    GAP_MAX = 72

    obs = []
    norm = []   # normalized 0..4 intensity per segment (drives the backdrop too)
    cx = 140.0  # first obstacle past the start so the player can react

    for i, raw in enumerate(intensity_bins):
        # normalize intensity to 0..4 buckets (GitHub-style levels)
        if raw <= 0:
            lvl = 0
        elif raw <= 1:
            lvl = 1
        elif raw <= 3:
            lvl = 2
        elif raw <= 6:
            lvl = 3
        else:
            lvl = 4
        norm.append(lvl)

        seg_end = (i + 1) * SEG + 140

        # RULE 1: baseline floor -- at least 1 obstacle per segment, so even an
        # all-zero (no-commit) user gets a real, rhythmic, completable level.
        count = 1 + lvl  # 1..5 obstacles, scales with intensity

        # RULE 2: intensity -> density. Higher lvl packs obstacles closer (down
        # to GAP_MIN, never below) so busy segments feel dense but stay fair.
        gap = GAP_MAX - lvl * 8
        if gap < GAP_MIN:
            gap = GAP_MIN

        placed = 0
        while placed < count and cx < seg_end:
            # quiet segments are all single spikes (gentle rhythm jumps); blocks
            # and spike-runs appear as intensity climbs.
            if lvl == 0:
                kind = "spike"
            else:
                kind = "block" if random.randint(0, 4) < lvl else "spike"

            if kind == "spike":
                run_n = 1 + (1 if lvl >= 3 and random.randint(0, 1) else 0)
                for s in range(run_n):
                    # busier segments occasionally swap a spike for a "bug" enemy
                    # (same hitbox, different sprite) for visual variety.
                    spr = "bug" if (lvl >= 2 and random.randint(0, 2) == 0) else "spike"
                    obs.append({"t": "spike", "spr": spr,
                                "x": int(cx) + s * 13, "w": 12, "h": 12})
                cx += 13 * run_n + gap
            else:
                bw = 14 + random.randint(0, 1) * 6
                bh = 8 + lvl * 5  # RULE 2: taller blocks in busy segments
                obs.append({"t": "block", "x": int(cx), "w": bw, "h": bh})
                cx += bw + gap
            placed += 1

        # if the segment under-filled (low intensity), advance to its end so the
        # next bin starts in its own slice of the track.
        if cx < seg_end:
            cx = float(seg_end)

    # level end marker = a bit past the last obstacle
    level_end = (obs[-1]["x"] + 80) if obs else 400

    # COLLECTIBLE STARS: scatter in clear gaps at jump-reachable heights (a real
    # reason to risk a jump). Deterministic (same seed) so a level is reproducible.
    pickups = []

    def _clear(x):
        for o in obs:
            if abs(o["x"] - x) < 24:
                return False
        return True

    sx = 200.0
    while sx < level_end - 40:
        if _clear(sx):
            # alternate low (skim) / mid (jump) heights for rhythm
            y = GROUND_Y - (30 if (int(sx) // 70) % 2 else 18)
            pickups.append({"x": int(sx), "y": y, "got": False})
        sx += 70
    return obs, level_end, norm, pickups


LEVEL_OBSTACLES, LEVEL_END, LEVEL_BINS, LEVEL_PICKUPS = build_level()


# ===========================================================================
# LEVEL CATALOG  (built-in + synced from github.com/<handle>/badge)
# ===========================================================================
# LEVELS is the merged, selectable list. SCROLL_NOW is the active level's speed
# (LEVEL_* globals above describe the active level's obstacles/backdrop).
LEVELS = list(BUILTIN_LEVELS)
SCROLL_NOW = SCROLL
sel_level = 0          # index into LEVELS on the level-select screen
sync_status = None     # transient status line on the select screen
sync_at = 0


def _clean_level(d):
    # validate one synced level dict -> normalized {name,bins,speed,src} or None
    try:
        name = str(d.get("name", "")).strip()
        bins = d.get("bins")
        if not name or not isinstance(bins, (list, tuple)) or not bins:
            return None
        bins = [int(b) for b in bins][:64]   # cap length (keeps it lean)
        spd = d.get("speed", None)
        spd = float(spd) if spd else SCROLL
        if spd < 30:
            spd = 30.0
        if spd > 160:
            spd = 160.0
        return {"name": name[:18], "bins": bins, "speed": spd, "src": "github"}
    except Exception:
        return None


def merge_levels(data):
    # built-ins first, then synced (skipping any that duplicate a built-in name)
    global LEVELS
    merged = list(BUILTIN_LEVELS)
    names = set(l["name"] for l in merged)
    for raw in (data or {}).get("levels", []):
        lv = _clean_level(raw)
        if lv and lv["name"] not in names:
            merged.append(lv)
            names.add(lv["name"])
    LEVELS = merged


def load_cached_levels():
    try:
        merge_levels(json.load(open(LEVELS_CACHE)))
    except Exception:
        LEVELS[:] = list(BUILTIN_LEVELS)   # offline-first: built-ins always work


load_cached_levels()
# restore last-played selection if it still exists in the catalog
for _i, _l in enumerate(LEVELS):
    if _l["name"] == store["last"]:
        sel_level = _i
        break


def apply_level(idx):
    # rebuild the active obstacle layout + backdrop from LEVELS[idx], set speed.
    global LEVEL_OBSTACLES, LEVEL_END, LEVEL_BINS, LEVEL_PICKUPS, SCROLL_NOW, sel_level
    sel_level = idx % len(LEVELS)
    lv = LEVELS[sel_level]
    LEVEL_OBSTACLES, LEVEL_END, LEVEL_BINS, LEVEL_PICKUPS = build_level(lv["bins"])
    SCROLL_NOW = lv.get("speed", SCROLL)
    store["last"] = lv["name"]
    State.save("commitdash", store)


# TODO (stretch): "Play My Graph" — a level built from the player's REAL GitHub
# contributions. The badge app fetches https://github.com/{user}.contribs into
# /contrib_data.json (53 weeks x 7 days of 0..4 "level" values). A future pass
# would: read that cached file (or fetch reboot-safely like trigger_sync), sum
# each week's daily levels into a per-segment "intensity", bin ~12-16 segments,
# and insert a synthetic level {"name":"My Graph","bins":[...]} at the top of
# LEVELS. Left as a stub so it can't half-break the offline-first flow.
def build_my_graph_level():
    return None   # not wired into the UI yet


# set the active level to the restored last-played (or first) selection
apply_level(sel_level)


# ===========================================================================
# GAME STATE
# ===========================================================================
class GS:
    INTRO = 1
    SELECT = 5
    PLAY = 2
    DEAD = 3
    WIN = 4


state = GS.INTRO
cam = 0.0           # world scroll offset (px) = distance travelled
py = float(GROUND_Y - CUBE)   # cube y (top-left); start grounded for the intro demo
vy = 0.0            # cube vertical velocity
grounded = True
rot = 0.0           # cube spin angle (visual)
dead_at = 0
dead_x = 0          # where the cube died (for the burst sprite)
dead_y = 0
particles = []      # death burst: [x, y, vx, vy]
stars = 0           # collectibles grabbed this run
sparkles = []       # collect bursts: [world_x, y, born_ms]


def reset_run():
    global cam, py, vy, grounded, rot, particles, state, stars, sparkles
    cam = 0.0
    py = GROUND_Y - CUBE
    vy = 0.0
    grounded = True
    rot = 0.0
    particles = []
    stars = 0
    sparkles = []
    for p in LEVEL_PICKUPS:      # re-arm collectibles for the replay
        p["got"] = False
    state = GS.PLAY
    store["attempts"] += 1
    State.save("commitdash", store)


# ===========================================================================
# PHYSICS / COLLISION
# ===========================================================================
def cube_rect():
    return (PLAYER_X, int(py), CUBE, CUBE)


def obstacle_screen_x(o):
    return o["x"] - cam


def aabb(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def step_physics(dt):
    global py, vy, grounded, rot, state, dead_at, stars

    # vertical integrate
    vy += GRAVITY * dt
    py += vy * dt
    if vy > 0:
        rot = 0.0  # settle spin when falling onto a surface check below

    # spin while airborne (visual squash/rotate feel, cheap)
    if not grounded:
        rot += dt * 7.0

    cx, cy, cw, ch = cube_rect()
    landed_y = None
    grounded = False

    # ground floor
    if py + CUBE >= GROUND_Y:
        landed_y = GROUND_Y - CUBE

    # obstacle collisions
    for o in LEVEL_OBSTACLES:
        ox = obstacle_screen_x(o)
        if ox > 170 or ox + o["w"] < -4:
            continue
        if o["t"] == "spike":
            # spike = triangle; use a slightly inset box as the deadly hit.
            sx = ox + 2
            stop = GROUND_Y - o["h"]
            if aabb(cx + 2, cy + 2, cw - 4, ch - 2, sx, stop + 3, o["w"] - 4, o["h"] - 3):
                die()
                return
        else:
            btop = GROUND_Y - o["h"]
            # landing on top: feet near the block top and moving down
            if vy >= 0 and cx + cw > ox + 1 and cx < ox + o["w"] - 1:
                if cy + ch >= btop and cy + ch <= btop + 10 + vy * dt:
                    cand = btop - CUBE
                    if landed_y is None or cand < landed_y:
                        landed_y = cand
                        continue
            # otherwise, overlapping the block body = side hit = death
            if aabb(cx + 1, cy + 1, cw - 2, ch - 2, ox, btop, o["w"], o["h"]):
                # allow the top-landing case handled above; this is a real side hit
                if not (vy >= 0 and cy + ch <= btop + 8):
                    die()
                    return

    if landed_y is not None and py >= landed_y - 0.5:
        py = landed_y
        vy = 0.0
        grounded = True
        rot = round(rot / (math.pi / 2)) * (math.pi / 2)  # snap to flat

    # collectible stars (overlap = grab -> score + sparkle burst)
    for p in LEVEL_PICKUPS:
        if p["got"]:
            continue
        psx = p["x"] - cam
        if -16 < psx < 176 and aabb(cx, cy, cw, ch, psx - 5, p["y"] - 5, 10, 10):
            p["got"] = True
            stars += 1
            sparkles.append([p["x"], p["y"], badge.ticks])

    # win check
    if cam >= LEVEL_END:
        state = GS.WIN
        record_progress()


def die():
    global state, dead_at, particles, dead_x, dead_y
    state = GS.DEAD
    dead_at = badge.ticks
    record_progress()
    cx, cy, _, _ = cube_rect()
    dead_x = cx + CUBE // 2
    dead_y = cy + CUBE // 2
    particles = []
    for _ in range(14):
        particles.append([cx + 7, cy + 7,
                           random.randint(-60, 60), random.randint(-90, 10)])


def record_progress():
    pct = int(min(100, cam / LEVEL_END * 100))
    dist = int(cam)
    changed = False
    if pct > store["best_pct"]:
        store["best_pct"] = pct
        changed = True
    if dist > store["best_dist"]:
        store["best_dist"] = dist
        changed = True
    if stars > store["best_stars"]:
        store["best_stars"] = stars
        changed = True
    # per-level best %
    name = LEVELS[sel_level]["name"]
    if pct > store["best_by"].get(name, 0):
        store["best_by"][name] = pct
        changed = True
    if changed:
        State.save("commitdash", store)


def do_jump():
    global vy, grounded
    if grounded:
        vy = JUMP_V_HELD if badge.held(BUTTON_A) else JUMP_V
        grounded = False


# ===========================================================================
# DRAWING
# ===========================================================================
def draw_grid():
    # Base fill = the GitHub dark + a single empty-cell band so the gaps between
    # green cells read as a grid WITHOUT drawing every empty cell (big FPS win:
    # we only emit fills for the lit green cells, ~1/3 of the field).
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, GROUND_Y))
    screen.pen = GRID_EMPTY
    screen.shape(shape.rectangle(0, GRID_TOP, 160, GRID_BOTTOM - GRID_TOP))

    icam = int(cam * 0.4)      # PARALLAX: backdrop scrolls slower -> reads far away
    col0 = icam // CELL
    px_off = icam % CELL
    icamf = int(cam)           # true world pos -> which segment we're running through
    t = badge.ticks
    flickk = (t // 260) % 12
    cols = 160 // CELL + 2
    rows = (GRID_BOTTOM - GRID_TOP) // CELL
    rect = shape.rectangle  # local alias (faster lookups in the hot loop)
    nb = len(LEVEL_BINS)

    for c in range(cols):
        wcol = col0 + c
        sx = c * CELL - px_off
        # DYNAMIC: the backdrop graph thickens/brightens under busy segments and
        # thins out under quiet ones (env = this column's segment intensity 0..4,
        # the same data that drives obstacles -> real commits later).
        env = LEVEL_BINS[((icamf + sx) // SEG) % nb] if nb else 2
        thresh = 206 - env * 26          # busy -> lower thresh -> more cells lit
        base = wcol * 73
        for r in range(rows):
            h = (base + r * 19 + wcol * r) & 0xFF
            if h <= thresh:
                continue
            lvl = min(3, env)            # busy segment -> brighter distant cells
            if h > 236:
                lvl = min(3, lvl + 1)
            if ((wcol * 7 + r) % 12) == flickk:   # subtle flicker pulse
                lvl = min(3, lvl + 1)
            screen.pen = GH_BG[lvl]               # DIM palette = the distant graph
            screen.shape(rect(sx, GRID_TOP + r * CELL, CELL - 1, CELL - 1))


def draw_ground():
    screen.pen = GROUND_DK
    screen.shape(shape.rectangle(0, GROUND_Y, 160, 120 - GROUND_Y))
    screen.pen = GROUND
    screen.shape(shape.rectangle(0, GROUND_Y, 160, 2))
    # moving tick marks so speed reads on the ground
    screen.pen = GROUND
    off = int(cam) % 16
    for gx in range(-off, 160, 16):
        screen.shape(shape.rectangle(gx, GROUND_Y + 5, 2, 2))


def _spike(cx, base_y, half_w, h, pen):
    # upward triangle via a 3-sided regular polygon, scaled to a spike.
    # regular_polygon points up by default; place its centroid so the apex
    # sits at (cx, base_y - h) and the base sits on (base_y).
    tri = shape.regular_polygon(0, 0, 1.0, 3)
    # In this firmware regular_polygon(...,3) renders apex DOWN (base on top).
    # Mirror vertically (negative y-scale) so the apex points UP, then place the
    # base on base_y. After mirroring: apex local y = +1*sy, base = -0.5*sy.
    # With sy = -(h/1.5): apex at -h/1.5 (up), base at +h/3 (down). Translate so
    # base sits on base_y.
    tri.transform = mat3().translate(cx, base_y - h / 3.0) \
        .scale(half_w / 0.866, -h / 1.5)
    screen.pen = pen
    screen.shape(tri)


def draw_finish():
    # portal marking the end of the level (sits on the ground at LEVEL_END)
    fx = LEVEL_END - cam
    if -SP_FIN.width < fx < 168:
        screen.blit(SP_FIN, vec2(int(fx), GROUND_Y - SP_FIN.height))


def draw_obstacles():
    for o in LEVEL_OBSTACLES:
        ox = obstacle_screen_x(o)
        if ox > 168 or ox + o["w"] < -4:
            continue
        x = int(ox)
        top = GROUND_Y - o["h"]
        # sprite scaled to the obstacle's logical rect (collision unchanged)
        if o["t"] == "spike":
            img = SP_BUG if o.get("spr") == "bug" else SP_SPIKE
        else:
            img = SP_BLOCK
        screen.blit(img, rect(x, top, o["w"], o["h"]))


def draw_pickups():
    for p in LEVEL_PICKUPS:
        if p["got"]:
            continue
        psx = p["x"] - cam
        if -SP_STAR.width < psx < 168:
            bob = int(2 * math.sin((badge.ticks + p["x"]) / 240.0))
            y = p["y"] + bob
            # dark halo so the green star pops against the bright-green grid
            screen.pen = color.rgb(0, 0, 0, 110)
            screen.shape(shape.circle(int(psx) + 5, y + 5, 8))
            screen.blit(SP_STAR, vec2(int(psx), y))


def draw_sparkles():
    now = badge.ticks
    live = []
    for s in sparkles:
        age = now - s[2]
        if age < 320:
            sz = 10 + age // 14            # expand 10 -> ~32px
            sx_ = s[0] - cam
            screen.blit(SP_SPARK, rect(int(sx_ - sz / 2), int(s[1] - sz / 2), sz, sz))
            live.append(s)
    sparkles[:] = live


def draw_cube():
    cx, cy, cw, ch = cube_rect()
    # ground shadow: shrinks as the cube rises (anchors it + adds depth)
    air = max(0, (GROUND_Y - CUBE) - int(cy))
    sh_w = max(3, cw - min(air // 5, cw - 3))
    screen.pen = color.rgb(7, 14, 10)
    screen.shape(shape.rounded_rectangle(cx + (cw - sh_w) // 2, GROUND_Y - 1, sh_w, 2, 1))
    # sprite player: grounded run pose vs. airborne spin pose
    screen.blit(SP_RUN if grounded else SP_AIR, rect(cx, cy, cw, ch))


def draw_hud():
    # progress bar across the very top
    pct = min(1.0, cam / LEVEL_END)
    screen.pen = color.rgb(0, 0, 0, 120)
    screen.shape(shape.rectangle(0, 0, 160, 6))
    screen.pen = GH[1]
    screen.shape(shape.rectangle(1, 1, 158, 4))
    screen.pen = GH[3]
    screen.shape(shape.rectangle(1, 1, int(158 * pct), 4))

    # distance / attempt readouts
    screen.font = F_TINY
    screen.pen = WHITE
    screen.text("%dm" % int(cam), 3, 8)
    a = "A%d" % store["attempts"]
    w, _ = screen.measure_text(a)
    screen.pen = MUTED
    screen.text(a, 157 - w, 8)
    # collectible-star counter, centred up top
    sc = "%d" % stars
    sw, _ = screen.measure_text(sc)
    gx = 80 - (9 + 2 + sw) // 2
    screen.blit(SP_STAR, rect(gx, 7, 9, 9))
    screen.pen = GOLD
    screen.text(sc, gx + 11, 8)


def draw_particles(dt):
    for p in particles:
        p[0] += p[2] * dt
        p[1] += p[3] * dt
        p[3] += GRAVITY * dt
    screen.pen = PLAYER
    for p in particles:
        screen.shape(shape.rectangle(int(p[0]), int(p[1]), 3, 3))


def center(txt, y, fnt, pen):
    screen.font = fnt
    w, _ = screen.measure_text(txt)
    screen.pen = pen
    screen.text(txt, int(80 - w / 2), int(y))


# ===========================================================================
# LEVEL SYNC + SELECT  (reboot-safe one-frame fetch, mirrors the agenda app)
# ===========================================================================
def draw_syncing():
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    draw_grid()
    draw_ground()
    screen.pen = color.rgb(0, 0, 0, 170)
    screen.shape(shape.rounded_rectangle(18, 40, 124, 40, 5))
    center("Syncing levels...", 48, F_SM, GH[3])
    center(ghbadge.handle() + "/badge", 64, F_TINY, MUTED)


def trigger_sync():
    # reboot-safe: paint the syncing screen, push it ONCE, then block on Wi-Fi +
    # HTTP inside THIS frame so display.update() can't fire mid-association.
    global sync_status, sync_at
    draw_syncing()
    display.update()
    status, data = ghbadge.fetch_json("commitdash/levels.json")
    if status == "ok":
        try:
            merge_levels(data)
            fsutil.write_json(LEVELS_CACHE, data)
            n = len(LEVELS) - len(BUILTIN_LEVELS)
            sync_status = "Synced %d level%s" % (n, "" if n == 1 else "s")
        except Exception:
            sync_status = "levels.json format error"
    elif status == "not_found":
        sync_status = "add commitdash/levels.json"
    elif status == "no_wifi":
        sync_status = "No Wi-Fi set up"
    elif status == "rate_limited":
        sync_status = "GitHub busy - retry"
    else:
        sync_status = "Sync failed"
    sync_at = badge.ticks
    return None


# level-select rows: the catalog + a trailing "Sync levels" action button.
SEL_TOP = 30
SEL_ROW = 13
SEL_VISIBLE = 5


def _sel_rows():
    return len(LEVELS) + 1   # +1 = the "Sync levels" action at the bottom


def select_screen():
    global sel_level, sync_status
    n = len(LEVELS)
    rows = _sel_rows()
    sync_row = n   # last index = the sync action

    if badge.pressed(BUTTON_UP):
        sel_level = (sel_level - 1) % rows
    if badge.pressed(BUTTON_DOWN):
        sel_level = (sel_level + 1) % rows
    if badge.pressed(BUTTON_A):
        if sel_level == sync_row:
            return trigger_sync()
        apply_level(sel_level)
        reset_run()
        return None

    # --- draw ---
    screen.pen = BG
    screen.shape(shape.rectangle(0, 0, 160, 120))
    screen.pen = color.rgb(20, 26, 34)
    screen.shape(shape.rectangle(0, 0, 160, 16))
    screen.font = F_SM
    screen.pen = GH[3]
    screen.text("LEVELS", 6, 4)
    screen.pen = MUTED
    screen.font = F_TINY
    hint = "UP/DN  A=go"
    hw, _ = screen.measure_text(hint)          # right-align so it never clips the edge
    screen.text(hint, 156 - hw, 5)

    # scroll window so the selection stays visible
    first = 0
    if sel_level >= SEL_VISIBLE:
        first = sel_level - SEL_VISIBLE + 1
    if first > rows - SEL_VISIBLE:
        first = max(0, rows - SEL_VISIBLE)

    y = SEL_TOP
    for i in range(first, min(rows, first + SEL_VISIBLE)):
        on = (i == sel_level)
        if on:
            screen.pen = GH_BG[3]
            screen.shape(shape.rounded_rectangle(4, y - 2, 152, SEL_ROW - 1, 3))
            screen.pen = GH[3]
            screen.shape(shape.rectangle(4, y - 2, 2, SEL_ROW - 1))
        if i == sync_row:
            screen.font = F_SM
            screen.pen = GOLD if on else MUTED
            screen.text("> Sync levels", 12, y)
        else:
            lv = LEVELS[i]
            screen.font = F_SM
            screen.pen = WHITE if on else MUTED
            screen.text(lv["name"], 12, y)
            # tag: synced vs built-in + best%
            tag = "sync" if lv.get("src") == "github" else "base"
            screen.font = F_TINY
            screen.pen = GH[2] if lv.get("src") == "github" else color.rgb(70, 84, 78)
            tw, _ = screen.measure_text(tag)
            screen.text(tag, 124 - tw, y + 1)
            bp = store["best_by"].get(lv["name"], 0)
            if bp:
                bs = "%d%%" % bp
                screen.pen = GOLD
                bw, _ = screen.measure_text(bs)
                screen.text(bs, 154 - bw, y + 1)
        y += SEL_ROW

    # scrollbar
    if rows > SEL_VISIBLE:
        track = SEL_VISIBLE * SEL_ROW
        bar = max(8, int(track * SEL_VISIBLE / rows))
        bp = int((track - bar) * first / max(1, rows - SEL_VISIBLE))
        screen.pen = color.rgb(30, 36, 44)
        screen.shape(shape.rounded_rectangle(157, SEL_TOP, 2, track, 1))
        screen.pen = MUTED
        screen.shape(shape.rounded_rectangle(157, SEL_TOP + bp, 2, bar, 1))

    # transient sync status footer
    if sync_status is not None and badge.ticks - sync_at < 3500:
        screen.pen = color.rgb(0, 0, 0, 160)
        screen.shape(shape.rectangle(0, 105, 160, 15))
        center(sync_status, 108, F_TINY, GH[3])
    else:
        sync_status = None
    return None


# ===========================================================================
# STATES
# ===========================================================================
def play(dt):
    global cam
    if badge.pressed(BUTTON_A) or badge.pressed(BUTTON_UP):
        do_jump()
    cam += SCROLL_NOW * dt
    step_physics(dt)

    draw_grid()
    draw_ground()
    draw_obstacles()
    draw_pickups()
    draw_finish()
    draw_cube()
    draw_sparkles()
    draw_hud()


def intro():
    draw_grid()
    draw_ground()
    # demo obstacles + cube sitting on the ground
    screen.blit(SP_SPIKE, rect(112, GROUND_Y - 12, 12, 12))
    screen.blit(SP_BLOCK, rect(132, GROUND_Y - 16, 16, 16))
    draw_cube()
    draw_hud()
    screen.pen = color.rgb(0, 0, 0, 150)
    screen.shape(shape.rounded_rectangle(16, 22, 128, 60, 5))
    center("COMMIT DASH", 26, F_BIG, GH[3])
    center("A / UP = jump", 44, F_SM, WHITE)
    center("Dash the graph!", 54, F_SM, MUTED)
    center("Best: %d%%" % store["best_pct"], 66, F_SM, GOLD)
    if (badge.ticks // 500) % 2:
        center("Press A to start", 90, F_SM, GH[3])
    if badge.pressed(BUTTON_A):
        global state
        state = GS.SELECT


def dead(dt):
    draw_grid()
    draw_ground()
    draw_obstacles()
    draw_pickups()
    draw_finish()
    draw_sparkles()
    age = badge.ticks - dead_at
    # expanding explosion sprite at the crash point (first ~260ms)
    if age < 260:
        bsz = 14 + age // 12          # grows 14 -> ~35px
        screen.blit(SP_BURST, rect(int(dead_x - bsz / 2), int(dead_y - bsz / 2), bsz, bsz))
    draw_particles(dt)
    if age < 140:  # white flash
        screen.pen = color.rgb(255, 255, 255, max(0, 180 - age))
        screen.shape(shape.rectangle(0, 0, 160, 120))
    draw_hud()
    screen.pen = color.rgb(0, 0, 0, 150)
    screen.shape(shape.rounded_rectangle(20, 30, 120, 52, 5))
    center("CRASHED", 36, F_BIG, RED)
    center("Got %d%%" % min(100, int(cam / LEVEL_END * 100)), 52, F_SM, WHITE)
    if (badge.ticks // 400) % 2:
        center("A = retry   B = levels", 68, F_TINY, GH[3])
    global state
    if badge.pressed(BUTTON_A):
        reset_run()          # replays the SELECTED level
    elif badge.pressed(BUTTON_B):
        state = GS.SELECT


def win():
    draw_grid()
    draw_ground()
    center("LEVEL COMPLETE", 36, F_BIG, GH[3])
    center(LEVELS[sel_level]["name"], 52, F_SM, WHITE)
    center("100%  -  nice streak!", 62, F_SM, GOLD)
    if (badge.ticks // 500) % 2:
        center("A = again   B = levels", 80, F_TINY, WHITE)
    draw_hud()
    global state
    if badge.pressed(BUTTON_A):
        reset_run()
    elif badge.pressed(BUTTON_B):
        state = GS.SELECT


def update():
    dt = badge.ticks_delta / 1000.0
    if dt > 0.05:
        dt = 0.05  # clamp huge frames (don't tunnel through obstacles)
    if state == GS.INTRO:
        intro()
    elif state == GS.SELECT:
        return select_screen()
    elif state == GS.PLAY:
        play(dt)
    elif state == GS.DEAD:
        dead(dt)
    else:
        win()
    return None


run(update)
