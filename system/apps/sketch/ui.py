import math
import badgeware  # noqa: F401  (ensures builtins: screen, color, shape, vec2, image, pixel_font, SpriteSheet, badge)

screen.antialias = X2
canvas_area = (10, 15, 140, 85)

font = pixel_font.load("/system/assets/fonts/vest.ppf")
mona = SpriteSheet("/system/assets/mona-sprites/mona-dance.png", 6, 1).animation()


def _scale_blit(img, x, y, w, h):
    dx, dy = x, y
    if w < 0:
        dx = x + w
        w = -w
    if h < 0:
        dy = y + h
        h = -h
    if w < 1:
        w = 1
    if h < 1:
        h = 1
    screen.blit(img, rect(int(dx), int(dy), int(w), int(h)))


def draw_mona(pos, direction):
    frame = int(badge.ticks / 150)
    _scale_blit(mona.frame(frame), pos[0], pos[1], 28 * direction, 24)


def draw_background():
    # fill the background in that classic red...
    screen.pen = color.rgb(170, 45, 40)
    screen.shape(shape.rectangle(0, 0, 160, 120))

    # draw the embossed gold logo
    screen.font = font
    w, _ = screen.measure_text("MonaSketch")
    screen.pen = color.rgb(240, 210, 160)
    screen.text("MonaSketch", int(80 - (w / 2) - 1), int(-1))
    screen.pen = color.rgb(190, 140, 80, 100)
    screen.text("MonaSketch", int(80 - (w / 2)), int(0))

    # draw the canvas area grey background and screen shadows
    screen.pen = color.rgb(210, 210, 210)
    screen.shape(shape.rounded_rectangle(*canvas_area, 6))
    screen.pen = color.rgb(180, 180, 180)
    screen.shape(
        shape.rounded_rectangle(
            canvas_area[0] + 3, canvas_area[1], canvas_area[2] - 5, 3, 2
        )
    )
    screen.shape(
        shape.rounded_rectangle(
            canvas_area[0], canvas_area[1] + 3, 3, canvas_area[3] - 5, 2
        )
    )

    # draw highlights on the plastic "curve"
    screen.pen = color.rgb(255, 255, 255, 100)
    screen.shape(
        shape.rectangle(
            canvas_area[0] - 3, canvas_area[1] + 5, 1, canvas_area[3] - 10
        )
    )
    screen.shape(
        shape.rectangle(
            canvas_area[0] + canvas_area[2] + 2,
            canvas_area[1] + 5,
            1,
            canvas_area[3] - 10,
        )
    )


left_dial_angle = 0
right_dial_angle = 0


def draw_dial(angle, pos):
    radius = 16

    # calculate an offset to fake perspective on the dials
    offset = (80 - pos[0]) / 35

    # draw the dial shadow
    screen.pen = color.rgb(0, 0, 0, 40)
    screen.shape(shape.circle(pos[0] + offset * 1.5, pos[1], radius + 2))

    # draw the dial shaft
    screen.pen = color.rgb(150, 160, 170)
    screen.shape(shape.circle(pos[0] + offset, pos[1], radius))

    # draw the dial surface
    screen.pen = color.rgb(220, 220, 230)
    screen.shape(shape.circle(*pos, radius))

    # draw the animated ticks around the dial edge
    screen.pen = color.rgb(190, 190, 220)
    ticks = 20
    for i in range(ticks):
        deg = angle + (i * 360 / ticks)
        r = deg * (math.pi / 180.0)

        # tick inner and outer points
        outer = (pos[0] + math.sin(r) * radius, pos[1] + math.cos(r) * radius)
        inner = (
            pos[0] + math.sin(r) * (radius - 3),
            pos[1] + math.cos(r) * (radius - 3),
        )

        screen.shape(shape.line(*inner, *outer, 1.5))


def draw_cursor(cursor):
    cx = int(cursor[0] + canvas_area[0])
    cy = int(cursor[1] + canvas_area[1])
    # v2.0.2 has no XOR brush; emulate an always-visible cursor with a dark halo
    # plus a pulsing bright core so it stands out on any drawn background.
    arms = ((2, 0, 2, 1), (-3, 0, 2, 1), (0, 2, 1, 2), (0, -3, 1, 2))
    screen.pen = color.rgb(0, 0, 0, 180)  # halo
    for ax, ay, aw, ah in arms:
        screen.shape(shape.rectangle(cx + ax - 1, cy + ay - 1, aw + 2, ah + 2))
    pulse = int((math.sin(badge.ticks / 250) * 0.5 + 0.5) * 155) + 100
    screen.pen = color.rgb(pulse, pulse, pulse)  # pulsing bright core
    for ax, ay, aw, ah in arms:
        screen.shape(shape.rectangle(cx + ax, cy + ay, aw, ah))
