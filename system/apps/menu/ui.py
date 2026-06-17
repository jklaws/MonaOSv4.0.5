import math
import random
import badgeware  # noqa: F401  (builtins: color, shape, badge, screen, mat3)

black = color.rgb(0, 0, 0)
background = color.rgb(35, 41, 37)
phosphor = color.rgb(211, 250, 55)
terminal_text = color.rgb(60, 71, 16)
terminal_fade = color.rgb(35, 41, 37, 150)


def draw_background():
    screen.pen = black
    screen.shape(shape.rectangle(0, 0, 10, 10))
    screen.shape(shape.rectangle(150, 0, 10, 10))
    screen.shape(shape.rectangle(0, 110, 10, 10))
    screen.shape(shape.rectangle(150, 110, 10, 10))

    screen.pen = background
    screen.shape(shape.rounded_rectangle(0, 0, 160, 120, 8))

    draw_terminal()


class Terminal:
    lines = []
    max_lines = 25
    line_added_at = 0
    lines_added = 0
    speed = 250

    def update():
        if badge.ticks - Terminal.line_added_at > Terminal.speed:
            Terminal.add_line()

    def add_line():
        Terminal.lines.append(random.randint(20, 100))
        Terminal.line_added_at = badge.ticks
        Terminal.lines_added += 1
        if len(Terminal.lines) > Terminal.max_lines:
            Terminal.lines = Terminal.lines[len(Terminal.lines) - Terminal.max_lines:]


for _ in range(25):
    Terminal.add_line()


def draw_terminal():
    screen.pen = terminal_text
    Terminal.update()

    rct = shape.rectangle(0, 0, 1, 1)
    for i in range(21):
        y = 20 + i * 5
        yo = ((badge.ticks - Terminal.line_added_at) / Terminal.speed) * 5
        y = int(y - yo)
        random.seed(i + Terminal.lines_added)
        cx = 0
        while cx < Terminal.lines[i]:
            w = random.randint(3, 10)
            rct.transform = mat3().translate(cx + 5, y).scale(w, 2)
            screen.shape(rct)
            cx += w + 2

    screen.pen = terminal_fade
    screen.shape(shape.rectangle(0, 15, 160, 5))
    screen.shape(shape.rectangle(0, 15, 160, 3))


def draw_header():
    dots = "." * int(math.sin(badge.ticks / 250) * 2 + 2)
    label = f"Mona-OS v4.0.5{dots}"

    screen.pen = phosphor
    screen.text(label, 5, 2)

    if badge.is_charging():
        battery_level = (badge.ticks / 20) % 100
    else:
        battery_level = badge.battery_level()
    pos = (137, 4)
    size = (16, 8)
    screen.pen = phosphor
    screen.shape(shape.rectangle(pos[0], pos[1], size[0], size[1]))
    screen.shape(shape.rectangle(pos[0] + size[0], pos[1] + 2, 1, 4))
    screen.pen = background
    screen.shape(shape.rectangle(pos[0] + 1, pos[1] + 1, size[0] - 2, size[1] - 2))

    width = ((size[0] - 4) / 100) * battery_level
    screen.pen = phosphor
    screen.shape(shape.rectangle(pos[0] + 2, pos[1] + 2, width, size[1] - 4))
