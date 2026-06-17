import math
import badgeware  # noqa: F401  (builtins: color, shape, badge, mat3, screen, rect, vec2)

# bright icon colours
bold = [
    color.rgb(211, 250, 55),
    color.rgb(48, 148, 255),
    color.rgb(95, 237, 131),
    color.rgb(225, 46, 251),
    color.rgb(216, 189, 14),
    color.rgb(255, 128, 210),
]

fade = 1.8
faded = [
    color.rgb(int(211 / fade), int(250 / fade), int(55 / fade)),
    color.rgb(int(48 / fade), int(148 / fade), int(255 / fade)),
    color.rgb(int(95 / fade), int(237 / fade), int(131 / fade)),
    color.rgb(int(225 / fade), int(46 / fade), int(251 / fade)),
    color.rgb(int(216 / fade), int(189 / fade), int(14 / fade)),
    color.rgb(int(255 / fade), int(128 / fade), int(210 / fade)),
]

squircle = shape.squircle(0, 0, 20, 4)
shade_brush = color.rgb(0, 0, 0, 30)


def _scale_blit(img, x, y, w, h):
    # Port of old screen.scale_blit; v2.0.2 uses blit(src, dest_rect).
    dx, dy = x, y
    if w < 0:
        dx = x + w; w = -w
    if h < 0:
        dy = y + h; h = -h
    if w < 1: w = 1
    if h < 1: h = 1
    screen.blit(img, rect(int(dx), int(dy), int(w), int(h)))


class Icon:
    active_icon = None

    def __init__(self, pos, name, index, icon):
        self.active = False
        self.pos = pos
        self.icon = icon
        self.name = name
        self.index = index
        self.spin = False

    def activate(self, active):
        if not self.active and active:
            self.spin = True
            self.spin_start = badge.ticks
        self.active = active
        if active:
            Icon.active_icon = self

    def draw(self):
        width = 1
        sprite_width = self.icon.width
        sprite_offset = sprite_width / 2

        if self.spin:
            speed = 100
            frame = badge.ticks - self.spin_start
            width = round(math.cos(frame / speed) * 3) / 3
            width = max(0.1, width) if width > 0 else min(-0.1, width)
            sprite_width = width * self.icon.width
            sprite_offset = abs(sprite_width) / 2
            if frame > (speed * 6):
                self.spin = False

        squircle.transform = mat3().translate(*self.pos).scale(width, 1)

        screen.pen = shade_brush
        squircle.transform = squircle.transform.scale(1.1, 1.1)
        screen.shape(squircle)

        squircle.transform = squircle.transform.scale(1 / 1.1, 1 / 1.1)
        if self.active:
            screen.pen = bold[self.index]
        else:
            screen.pen = faded[self.index]
        squircle.transform = squircle.transform.translate(-1, -1)
        screen.shape(squircle)
        squircle.transform = squircle.transform.translate(2, 2)
        screen.pen = shade_brush
        screen.shape(squircle)

        if sprite_width > 0:
            self.icon.alpha = 255 if self.active else 100
            _scale_blit(
                self.icon,
                self.pos[0] - sprite_offset - 1,
                self.pos[1] - 13,
                sprite_width,
                24,
            )
