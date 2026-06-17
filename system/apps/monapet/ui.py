import math
import time
import badgeware  # noqa: F401  (ensures builtins: screen, color, shape, vec2, rect, SpriteSheet, badge, rom_font)

# load user interface sprites
icons = SpriteSheet("assets/icons.png", 4, 1)
arrows = SpriteSheet("assets/arrows.png", 3, 1)

# load in the font (v2.0.2: ROM font 'ark', loaded from /rom/fonts/ark.ppf)
screen.font = rom_font.ark

# brushes to match monas stats
stats_brushes = {
    "happy": color.rgb(141, 39, 135),
    "hunger": color.rgb(53, 141, 39),
    "clean": color.rgb(39, 106, 171),
    "warning": color.rgb(255, 0, 0, 200)
}

# icons to match monas stats
stats_icons = {
    "happy": icons.sprite(0, 0),
    "hunger": icons.sprite(1, 0),
    "clean": icons.sprite(2, 0)
}

# ui outline (contrast) colour
outline_brush = color.rgb(20, 30, 40, 150)
outline_brush_bold = color.rgb(20, 30, 40, 200)


# ---- 2.0 room: cozy, with a day/night cycle driven by the RTC clock ----------
def _lerp(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def time_of_day():
    try:
        h = time.localtime()[3]
    except Exception:
        h = 12
    if 7 <= h < 18:
        return "day"
    if 18 <= h < 21:
        return "dusk"
    return "night"


# wall_top, wall_bottom, sky, floor, floor_dark, dot(rgba)
PALETTES = {
    "day":   ((116, 170, 222), (158, 200, 236), (188, 226, 252),
              (198, 152, 100), (168, 124, 78),  (255, 255, 255, 28)),
    "dusk":  ((120, 92, 150),  (196, 130, 132),  (250, 178, 120),
              (150, 110, 82),  (118, 86, 64),   (255, 222, 180, 30)),
    "night": ((20, 24, 54),    (38, 42, 82),     (12, 16, 40),
              (74, 64, 96),    (54, 48, 74),    (180, 200, 255, 26)),
}


def background(mona):
    floor_y = int(mona.position()[1] - 5)
    mona_x = mona.position()[0]
    mx = (mona_x - 80) / 2

    tod = time_of_day()
    wall_top, wall_bot, sky, floor_c, floor_dk, dot = PALETTES[tod]

    # wall: a soft vertical gradient (a few bands)
    bands = 6
    bh = floor_y / bands
    for i in range(bands):
        screen.pen = color.rgb(*_lerp(wall_top, wall_bot, i / (bands - 1)))
        screen.shape(shape.rectangle(0, int(i * bh), 160, int(bh) + 1))

    # subtle dotted wallpaper (parallax with Mona)
    screen.pen = color.rgb(*dot)
    for yy in range(6, floor_y - 4, 16):
        for xx in range(6, 160, 16):
            screen.shape(shape.rectangle(int(xx - mx * 0.25), yy, 2, 2))

    # window on the left, showing the sky + sun / moon + stars
    wx = int(14 - mx * 0.3)
    wy, ww, wh = 14, 42, 34
    screen.pen = color.rgb(236, 238, 245)
    screen.shape(shape.rounded_rectangle(wx - 2, wy - 2, ww + 4, wh + 4, 4))
    screen.pen = color.rgb(*sky)
    screen.shape(shape.rounded_rectangle(wx, wy, ww, wh, 3))
    if tod == "night":
        screen.pen = color.rgb(232, 236, 246)
        screen.shape(shape.rounded_rectangle(wx + ww - 15, wy + 5, 9, 9, 4))   # moon
        screen.pen = color.rgb(255, 255, 255, 220)
        for sx, sy in ((7, 8), (18, 20), (28, 6), (13, 27), (34, 17), (22, 12)):
            screen.shape(shape.rectangle(wx + sx, wy + sy, 1, 1))
    else:
        screen.pen = color.rgb(255, 234, 150) if tod == "day" else color.rgb(255, 186, 120)
        screen.shape(shape.rounded_rectangle(wx + ww - 17, wy + 5, 11, 11, 5))  # sun
    screen.pen = color.rgb(236, 238, 245, 200)                                   # mullions
    screen.shape(shape.rectangle(wx + ww // 2 - 1, wy, 2, wh))
    screen.shape(shape.rectangle(wx, wy + wh // 2 - 1, ww, 2))

    # framed portrait of Mona on the right
    px = int(120 - mx)
    screen.pen = color.rgb(60, 46, 34)
    screen.shape(shape.rounded_rectangle(px, 18, 34, 30, 3))
    screen.pen = color.rgb(*_lerp(sky, (255, 255, 255), 0.15))
    screen.shape(shape.rounded_rectangle(px + 3, 20, 28, 26, 2))
    portrait = mona.anim("default").frame(0)
    screen.blit(portrait, rect(px + 4, 20, 26, 26))

    # skirting board
    screen.pen = color.rgb(*floor_dk)
    screen.shape(shape.rectangle(0, floor_y - 4, 160, 4))

    # floor (warm boards with a little perspective)
    floor = screen.window(0, floor_y, 160, 120)
    floor.pen = color.rgb(*floor_c)
    floor.shape(shape.rectangle(0, 0, 160, 120 - floor_y))
    floor.pen = color.rgb(*floor_dk)
    for i in range(0, 320, 14):
        x1 = i - ((mona_x - i) * 1.5)
        x2 = i - ((mona_x - i) * 2)
        floor.shape(shape.line(x1, 3, x2, 20, 1))


def draw_header(mona):
    screen.pen = outline_brush_bold
    screen.shape(shape.rounded_rectangle(2, -6, 156, 17, 3))

    # level (left) + name (center) + age in days (right); name turns red if sick
    screen.pen = color.rgb(255, 220, 120)
    screen.text("Lv%d" % mona.level(), 6, 1)
    screen.pen = stats_brushes["warning"] if mona.is_sick() else color.rgb(255, 255, 255)
    center_text("mona pet", 0)
    age = "%dd" % mona.age_days()
    w, _ = screen.measure_text(age)
    screen.pen = color.rgb(180, 200, 220)
    screen.text(age, 152 - w, 1)


def draw_button(x, y, label, active):
    width = 50

    bounce = math.sin(((badge.ticks / 20) - x) / 10) * 2

    screen.pen = color.rgb(255, 255, 255, 255 if active else 150)
    shadow_text(label, y + (bounce / 2), x, x + width)

    arrow = arrows.sprite(2, 0)
    arrow.alpha = 255 if active else 150
    screen.blit(arrow, vec2(x + (width / 2) - 4, y + bounce + 10))


def draw_bar(name, x, y, amount):
    bar_width = 50

    screen.pen = outline_brush
    screen.shape(shape.rounded_rectangle(x, y, bar_width, 12, 3))

    screen.pen = outline_brush
    screen.shape(shape.rounded_rectangle(x + 14, y + 3, bar_width - 17, 6, 2))

    fill_width = round(max(((bar_width - 17) / 100) * amount, 3))

    screen.pen = stats_brushes[name]
    if amount <= 30:
        blink = round(badge.ticks / 250) % 2 == 0
        if blink:
            screen.pen = stats_brushes["warning"]
    screen.shape(shape.rounded_rectangle(x + 14, y + 3, fill_width, 6, 2))

    screen.pen = color.rgb(210, 230, 250, 50)
    screen.shape(shape.rounded_rectangle(x + 15, y + 3, fill_width - 2, 1, 1))

    screen.blit(stats_icons[name], vec2(x, y))


def center_text(text, y, sx=0, ex=160):
    w, _ = screen.measure_text(text)
    screen.text(text, int(sx + ((ex - sx) / 2) - (w / 2)), int(y))


def shadow_text(text, y, sx=0, ex=160):
    temp = screen.pen
    screen.pen = color.rgb(0, 0, 0, 100)
    center_text(text, y + 1, sx + 1, ex + 1)
    screen.pen = temp
    center_text(text, y, sx, ex)
