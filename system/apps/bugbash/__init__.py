import sys
import os

sys.path.insert(0, "/system/apps/bugbash")
os.chdir("/system/apps/bugbash")

import badgeware  # noqa: F401  (builtins: screen, color, shape, rect, vec2, mat3, image, SpriteSheet, badge, run, BUTTON_*)
# AA ON: Bug Bash draws many vector shapes (HUD/bugs), so X2 smooths them
# noticeably. Measured cost is small: ~32fps -> ~29fps on RP2350 (still smooth).
screen.antialias = X2
import math
import random

big = pixel_font.load("/system/assets/fonts/absolute.ppf")
small = pixel_font.load("/system/assets/fonts/ark.ppf")

# ---- Mona sprite sheets: 0 idle, 1 blink, 2 walkA, 3 walkB, 4 windup, 5 strike, 6 hurt
# right-facing sheet + a pre-mirrored left-facing sheet (the firmware's blit does
# not flip on a negative-width rect, so we keep a real flipped copy)
sheet = SpriteSheet("/system/apps/bugbash/assets/mona.png", 7, 1)
sheet_l = SpriteSheet("/system/apps/bugbash/assets/mona_flip.png", 7, 1)
mona = sheet.animation(0, 0, 7)
mona_l = sheet_l.animation(0, 0, 7)
# super-spin attack: 6 frames (idle, windup, spin, tornado, spin, idle)
spin_sheet = SpriteSheet("/system/apps/bugbash/assets/spin.png", 6, 1)
spin_anim = spin_sheet.animation(0, 0, 6)
SPIN_SEQ = (1, 2, 3, 3, 4, 5)        # frame order across the move
portrait = image.load("/system/apps/bugbash/assets/portrait.png")
CELL = 44
OUTLINE = color.rgb(16, 20, 26)
CYAN = color.rgb(120, 205, 255)

# ---- enemy bug sprites: (name, points, speed_mult, hp) ----
BUG_TYPES = (
    ("cube", 1, 1.00, 1),
    ("ladybug", 1, 1.05, 1),
    ("spiky", 2, 1.15, 1),
    ("fly", 2, 1.35, 1),
    ("caterpillar", 3, 0.78, 2),
    ("beetle", 5, 0.70, 3),
)
BUG_IMG = []      # facing left (default art)
BUG_IMGF = []     # facing right (mirrored)
for _n, _p, _s, _h in BUG_TYPES:
    BUG_IMG.append(image.load("/system/apps/bugbash/assets/bug_%s.png" % _n))
    BUG_IMGF.append(image.load("/system/apps/bugbash/assets/bug_%s_f.png" % _n))


def pick_type():
    # introduce tougher bugs as levels climb; basics stay common
    if level >= 5 and random.random() < 0.08:
        return 5
    if level >= 4 and random.random() < 0.18:
        return 4
    avail = [0, 0, 1, 1]
    if level >= 2:
        avail.append(2)
    if level >= 3:
        avail.append(3)
    return random.choice(avail)

# ---- palette ----
WALL = color.rgb(46, 72, 78)
WALL2 = color.rgb(38, 60, 66)
FLOOR = color.rgb(150, 160, 172)
FLOOR2 = color.rgb(128, 138, 150)
TILE = color.rgb(112, 122, 134)
MACHINE = (color.rgb(86, 120, 200), color.rgb(150, 110, 200),
           color.rgb(90, 170, 130), color.rgb(190, 130, 150))
SCREENC = color.rgb(20, 30, 26)
SIGN = color.rgb(20, 24, 30)
WHITE = color.rgb(245, 248, 252)
LIME = color.rgb(211, 250, 55)
DIM = color.rgb(120, 138, 150)
RED = color.rgb(248, 81, 73)
REDDK = color.rgb(150, 36, 33)
GOLD = color.rgb(240, 196, 64)
GOLDDK = color.rgb(170, 130, 30)
BLACK = color.rgb(12, 12, 16)
PINK = color.rgb(249, 179, 221)

MONA_X = 80
MONA_TOP = 58          # blit y; feet land near y100
FEET_Y = 96
PUNCH_REACH = 50
CENTER_HIT = 15
GAME_MS = 45000        # per-level time
MAX_LIVES = 5
HEART_TTL = 4500       # ms a dropped heart waits to be collected
BANNER_MS = 1500       # "LEVEL n" intro
SPIN_MS = 750          # super-spin duration (also invulnerable while spinning)
SPIN_CHARGES = 2       # super-spins per level
HEART_HI_Y = 52        # collect with UP
HEART_LO_Y = 98        # collect with DOWN


class GS:
    INTRO = 1
    PLAYING = 2
    OVER = 3


state = GS.INTRO
score = 0
lives = 3
best = 0
level = 1
start_ms = 0
next_spawn = 0
banner_until = -9999
bugs = []              # {x,y,vx,kind}
splats = []            # {x,y,born,gold}
facing = 1             # 1 right, -1 left
punch_until = -9999
punch_dir = 1
hurt_until = -9999
invuln_until = -9999
hits = []              # {x,y,born} punch impact fx
heart = None           # {pos:"up"/"down", born} dropped collectible
next_heart_at = 0
spin_until = -9999      # super-spin animation/invuln window
spin_charges = SPIN_CHARGES
spin_ring = -9999       # shockwave fx start


def reset():
    global score, lives, level, start_ms, next_spawn, banner_until
    global bugs, splats, hits, heart, next_heart_at, spin_charges, spin_until
    global facing, punch_until, hurt_until, invuln_until
    score = 0
    lives = 3
    level = 1
    spin_charges = SPIN_CHARGES
    spin_until = -9999
    start_ms = badge.ticks + BANNER_MS
    next_spawn = badge.ticks + BANNER_MS + 500
    banner_until = badge.ticks + BANNER_MS
    bugs = []
    splats = []
    hits = []
    heart = None
    next_heart_at = badge.ticks + BANNER_MS + 9000
    facing = 1
    punch_until = hurt_until = invuln_until = -9999


def next_level():
    global level, start_ms, next_spawn, banner_until, bugs, heart, next_heart_at, spin_charges
    level += 1
    spin_charges = SPIN_CHARGES        # refill super-spins each level
    bugs = []
    heart = None
    start_ms = badge.ticks + BANNER_MS
    next_spawn = badge.ticks + BANNER_MS + 400
    banner_until = badge.ticks + BANNER_MS
    next_heart_at = badge.ticks + BANNER_MS + 8000


def elapsed():
    return badge.ticks - start_ms


def remaining():
    return max(0, GAME_MS - max(0, elapsed()))


def spawn_interval():
    return max(300, 1100 - (level - 1) * 110 - elapsed() // 60)


def bug_speed():
    return 0.28 + (level - 1) * 0.06 + max(0, elapsed()) / 100000.0


def spawn_bug():
    if len(bugs) >= 8:
        return
    ti = pick_type()
    _n, _p, sm, hp = BUG_TYPES[ti]
    left = random.randint(0, 1) == 0
    y = random.randint(82, 99)
    sp = bug_speed() * sm
    bugs.append({"x": -14 if left else 174, "y": y,
                 "vx": sp if left else -sp, "t": ti, "hp": hp, "flash": -999})


# ---------------- drawing ----------------

def _render_lab(g):
    # back wall
    g.pen = WALL
    g.shape(shape.rectangle(0, 0, 160, 70))
    # machines along the wall (body + screen only — keep prim count low)
    for i, mx in enumerate((6, 40, 110, 140)):
        g.pen = MACHINE[i % len(MACHINE)]
        g.shape(shape.rounded_rectangle(mx, 30, 18, 32, 2))
        g.pen = SCREENC
        g.shape(shape.rectangle(mx + 3, 34, 12, 9))
    # floor
    g.pen = FLOOR
    g.shape(shape.rectangle(0, 70, 160, 50))
    g.pen = FLOOR2
    g.shape(shape.rectangle(0, 70, 160, 3))
    # perspective tiles (fewer verticals — line draws are the lab's main cost)
    g.pen = TILE
    for i in range(-2, 8, 2):
        x = i * 30
        g.shape(shape.line(vec2(80 + (x - 80) * 0.55, 72), vec2(x, 120), 1))
    for ty in (84, 100):
        g.shape(shape.line(vec2(0, ty), vec2(160, ty), 1))


# Per-frame lab draw. (A cached full-screen image was tried but a 160x120 blit
# is actually SLOWER than these flat rect fills at AA-off — 25fps vs 38fps — so
# we redraw. Paletted sprites are the real win here: RAM, not framerate.)
def draw_lab():
    _render_lab(screen)


def draw_bug(bg):
    ti = bg["t"]
    img = BUG_IMGF[ti] if bg["vx"] > 0 else BUG_IMG[ti]   # face travel direction
    w, h = img.width, img.height
    bob = int(math.sin((badge.ticks + bg["x"] * 9) / 130) * 1.5)
    cx, cy = bg["x"], bg["y"]
    screen.blit(img, vec2(int(cx - w / 2), int(cy - h + bob)))
    if badge.ticks - bg["flash"] < 110:                   # hit flash
        screen.pen = color.rgb(255, 255, 255, 150)
        fl = shape.squircle(0, 0, w / 2, 3)
        fl.transform = mat3().translate(int(cx), int(cy - h / 2 + bob))
        screen.shape(fl)


def draw_bug_demo(cx, cy, ti):
    img = BUG_IMG[ti]
    screen.blit(img, vec2(int(cx - img.width / 2), int(cy - img.height)))


def draw_heart_pickup():
    t = badge.ticks
    age = t - heart["born"]
    up = heart["pos"] == "up"
    y = (HEART_HI_Y if up else HEART_LO_Y) + int(math.sin(t / 200) * 2)
    # fade out in the last 800ms
    left = HEART_TTL - age
    if left < 800 and (t // 100) % 2 == 0:
        return
    # glow ring
    screen.pen = color.rgb(255, 90, 110, 70)
    screen.shape(shape.circle(MONA_X, y, 9))
    _heart(MONA_X, y, 7.2, OUTLINE)
    _heart(MONA_X, y, 6.0, RED)
    screen.pen = color.rgb(255, 190, 190)
    screen.shape(shape.circle(MONA_X - 2, y - 2, 1.6))
    # direction hint arrow + key (regular_polygon points up by default)
    screen.pen = LIME
    ay = y - 13 if up else y + 13
    arr = shape.regular_polygon(0, 0, 4, 3)
    arr.transform = mat3().translate(MONA_X, ay).rotate(0 if up else math.pi)
    screen.shape(arr)
    octext("UP" if up else "DN", MONA_X, ay + (-9 if up else 4), small, WHITE)


def draw_mona():
    t = badge.ticks
    if t < spin_until:                       # super-spin animation
        prog = 1.0 - (spin_until - t) / SPIN_MS
        idx = SPIN_SEQ[min(len(SPIN_SEQ) - 1, int(prog * len(SPIN_SEQ)))]
        screen.blit(spin_anim.frame(idx), vec2(MONA_X - 22, MONA_TOP))
        return
    if t < hurt_until:
        idx = 6
    elif t < punch_until:
        idx = 5 if (punch_until - t) < 170 else 4
        face = punch_dir
    else:
        # idle with occasional blink + gentle bob
        idx = 1 if (t % 2600) < 160 else 0
    face = punch_dir if t < punch_until else facing
    # flicker during invulnerability
    if t < invuln_until and (t // 80) % 2 == 0 and t >= hurt_until:
        return
    anim = mona if face >= 0 else mona_l
    screen.blit(anim.frame(idx), vec2(MONA_X - 22, MONA_TOP))


def _heart(x, y, r, pen):
    screen.pen = pen
    screen.shape(shape.circle(x - r * 0.62, y - r * 0.35, r * 0.66))
    screen.shape(shape.circle(x + r * 0.62, y - r * 0.35, r * 0.66))
    tri = shape.regular_polygon(0, 0, r, 3)
    tri.transform = mat3().translate(x, y + r * 0.45).rotate(math.pi)
    screen.shape(tri)


def draw_heart(x, y, filled):
    # one heart shape (3 prims) instead of outline+fill+gloss (7)
    _heart(x, y, 4.2, RED if filled else color.rgb(74, 50, 50))


def otext(txt, x, y, fnt, fill):
    # chunky cartoon text: dark outline drawn 8 ways, then fill on top
    # single drop-shadow instead of a full outline: 2 glyph passes, not 5 —
    # HUD text is rendered every frame so this is a big saving
    screen.font = fnt
    screen.pen = OUTLINE
    screen.text(txt, x + 1, y + 1)
    screen.pen = fill
    screen.text(txt, x, y)


def octext(txt, cx, y, fnt, fill):
    screen.font = fnt
    w, _ = screen.measure_text(txt)
    otext(txt, int(cx - w / 2), y, fnt, fill)


def draw_hud():
    # left panel with white rounded border (portrait + hearts + score)
    panel = shape.rounded_rectangle(2, 2, 96, 28, 4)
    screen.pen = color.rgb(0, 0, 0, 120)
    screen.shape(panel)
    screen.pen = WHITE
    screen.shape(shape.stroke(panel, 1.5))
    screen.blit(portrait, vec2(4, 4))
    for i in range(MAX_LIVES):
        draw_heart(35 + i * 12, 9, i < lives)
    screen.font = small
    otext("Score:", 28, 19, small, WHITE)
    sw, _ = screen.measure_text("Score:")
    otext("%d" % score, 28 + sw + 3, 19, small, LIME)
    # timer (top-right, outlined, no panel — clear of the score panel)
    secs = remaining() // 1000
    octext("Time:", 133, 2, small, WHITE)
    octext("%d" % secs, 133, 11, big, LIME if secs > 10 else RED)
    octext("Lv %d" % level, 133, 25, small, WHITE)

    # super-spin charges (bottom-left): "B" + cyan pips that deplete
    otext("B", 5, 110, small, CYAN)
    for i in range(SPIN_CHARGES):
        screen.pen = CYAN if i < spin_charges else color.rgb(40, 55, 70)
        screen.shape(shape.circle(18 + i * 9, 113, 3))


def center(txt, y, fnt=big, pen=WHITE):
    screen.font = fnt
    w, _ = screen.measure_text(txt)
    screen.pen = pen
    screen.text(txt, int(80 - w / 2), int(y))


# ---------------- states ----------------

def do_punch(side):
    global punch_until, punch_dir, facing, score
    punch_until = badge.ticks + 260
    punch_dir = side
    facing = side
    # nearest bug in reach on that side
    best_i, best_d = -1, 999
    for i, bg in enumerate(bugs):
        dx = bg["x"] - MONA_X
        if side > 0 and 4 < dx < PUNCH_REACH and dx < best_d:
            best_i, best_d = i, dx
        elif side < 0 and 4 < -dx < PUNCH_REACH and -dx < best_d:
            best_i, best_d = i, -dx
    if best_i >= 0:
        bg = bugs[best_i]
        bg["flash"] = badge.ticks
        bg["hp"] -= 1
        bg["x"] -= 6 if bg["vx"] > 0 else -6        # knockback
        hits.append({"x": MONA_X + side * 24, "y": FEET_Y - 6, "born": badge.ticks})
        if bg["hp"] <= 0:
            bugs.pop(best_i)
            pts = BUG_TYPES[bg["t"]][1]
            score += pts
            splats.append({"x": bg["x"], "y": bg["y"], "born": badge.ticks, "pts": pts})


def do_spin():
    # super spin: one limited-use AoE that wipes EVERY bug on both sides
    # (ignores HP, so even caterpillars/beetles die), with i-frames while spinning
    global spin_until, spin_charges, score, invuln_until, spin_ring
    if spin_charges <= 0 or badge.ticks < spin_until or badge.ticks < hurt_until:
        return
    spin_charges -= 1
    spin_until = badge.ticks + SPIN_MS
    invuln_until = badge.ticks + SPIN_MS
    spin_ring = badge.ticks
    for bg in bugs:
        pts = BUG_TYPES[bg["t"]][1]
        score += pts * 2                       # spin kills are worth double
        splats.append({"x": bg["x"], "y": bg["y"], "born": badge.ticks, "pts": pts * 2})
    bugs[:] = []                                # clear the field


def lives_can_heal():
    return lives < MAX_LIVES


def heal():
    global lives
    lives = min(MAX_LIVES, lives + 1)


def hurt():
    global lives, hurt_until, invuln_until, state
    if badge.ticks < invuln_until:
        return
    lives -= 1
    hurt_until = badge.ticks + 380
    invuln_until = badge.ticks + 1000
    if lives <= 0:
        state = GS.OVER


def collect_heart():
    global heart, next_heart_at
    heal()
    hits.append({"x": MONA_X, "y": heart_y(heart), "born": badge.ticks})
    heart = None
    next_heart_at = badge.ticks + random.randint(11000, 17000)


def heart_y(h):
    return HEART_HI_Y if h["pos"] == "up" else HEART_LO_Y


def play():
    global state, next_spawn, heart, next_heart_at

    banner = badge.ticks < banner_until

    if not banner:
        if badge.pressed(BUTTON_A):
            do_punch(-1)
        if badge.pressed(BUTTON_C):
            do_punch(1)
        if badge.pressed(BUTTON_B):
            do_spin()

        # heart drop: spawn when none active and the player can use it
        if heart is None and badge.ticks >= next_heart_at and lives < MAX_LIVES:
            heart = {"pos": "up" if random.randint(0, 1) else "down",
                     "born": badge.ticks}
        # collect / expire
        if heart is not None:
            if badge.ticks - heart["born"] > HEART_TTL:
                heart = None
                next_heart_at = badge.ticks + random.randint(9000, 14000)
            elif heart["pos"] == "up" and badge.pressed(BUTTON_UP):
                collect_heart()
            elif heart["pos"] == "down" and badge.pressed(BUTTON_DOWN):
                collect_heart()

        # spawn bugs
        if badge.ticks >= next_spawn:
            spawn_bug()
            next_spawn = badge.ticks + spawn_interval()

        # move bugs / collisions
        for bg in list(bugs):
            bg["x"] += bg["vx"]
            if abs(bg["x"] - MONA_X) < CENTER_HIT:
                bugs.remove(bg)
                hurt()

        # time up -> advance a level (death is the only way out)
        if remaining() <= 0:
            next_level()

    # ---- draw ----
    draw_lab()
    bugs.sort(key=lambda b: b["y"])
    for bg in bugs:
        draw_bug(bg)
    if heart is not None:
        draw_heart_pickup()
    # super-spin shockwave: expanding cyan rings sweeping both sides
    sa = badge.ticks - spin_ring
    if sa < SPIN_MS:
        for k in (0, 1):
            rr = int((sa / SPIN_MS) * 150) - k * 40
            if rr > 0:
                screen.pen = color.rgb(120, 205, 255, max(0, 180 - sa // 3 - k * 60))
                screen.shape(shape.stroke(shape.circle(MONA_X, FEET_Y - 6, rr), 2))
    draw_mona()
    # punch impact bursts
    for h in list(hits):
        a = badge.ticks - h["born"]
        if a > 180:
            hits.remove(h)
            continue
        screen.pen = color.rgb(255, 255, 255, max(0, 220 - a))
        st = shape.star(h["x"], h["y"], 8 - a // 30, 3, 5)
        screen.shape(st)
    # splats + score popups
    for s in list(splats):
        a = badge.ticks - s["born"]
        if a > 320:
            splats.remove(s)
            continue
        p = a / 320
        screen.font = small
        screen.pen = color.rgb(211, 250, 55, max(0, int(255 * (1 - p))))
        txt = "+%d" % s["pts"]
        tw, _ = screen.measure_text(txt)
        screen.text(txt, int(s["x"] - tw / 2), int(s["y"] - 10 - p * 10))
    draw_hud()
    # level banner
    if badge.ticks < banner_until:
        screen.pen = color.rgb(0, 0, 0, 150)
        screen.shape(shape.rectangle(0, 44, 160, 34))
        octext("LEVEL %d" % level, 80, 52, big, LIME)


def intro():
    global state
    draw_lab()
    screen.blit(mona.frame(0), vec2(MONA_X - 22, MONA_TOP))
    draw_bug_demo(24, 94, 1)
    draw_bug_demo(136, 94, 5)
    screen.pen = color.rgb(0, 0, 0, 120)
    screen.shape(shape.rounded_rectangle(20, 24, 120, 60, 4))
    octext("BUG BASH", 80, 26, big, LIME)
    center("A / C  punch", 44, small, WHITE)
    center("UP / DN  grab hearts", 54, small, WHITE)
    center("B  super spin (x2)", 64, small, CYAN)
    center("Survive to level up!", 76, small, DIM)
    if int(badge.ticks / 500) % 2:
        center("Press B to start", 100, small, color.rgb(120, 220, 160))
    if badge.pressed(BUTTON_B):
        reset()
        state = GS.PLAYING


def game_over():
    global state, best
    if score > best:
        best = score
    draw_lab()
    screen.pen = color.rgb(0, 0, 0, 160)
    screen.shape(shape.rectangle(0, 0, 160, 120))
    octext("GAME OVER", 80, 24, big, RED)
    center("Reached level %d" % level, 46, small, WHITE)
    center("Bugs bashed: %d" % score, 58, small, WHITE)
    center("Best: %d" % best, 70, small, DIM)
    if int(badge.ticks / 500) % 2:
        center("Press B to play again", 96, small, color.rgb(120, 220, 160))
    if badge.pressed(BUTTON_B):
        state = GS.INTRO


def update():
    if state == GS.INTRO:
        intro()
    elif state == GS.PLAYING:
        play()
    else:
        game_over()
    return None


run(update)
