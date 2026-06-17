# MonaOS 4.0.5 boot screen — cosmic GitHub Universe '26 hero + animated loading
# bar. Runs once on cold boot; press any button to skip.
import sys
import os

sys.path.insert(0, "/system/apps/startup")
os.chdir("/system/apps/startup")

import badgeware  # noqa: F401

screen.antialias = X2
boot = image.load("/system/apps/startup/boot.png")

DURATION = 2600
_start = badge.ticks

NEON = color.rgb(63, 185, 80)
TRACK = color.rgb(34, 44, 54)
WHITE = color.rgb(235, 245, 255)

BX, BY, BW, BH = 24, 104, 112, 5


def update():
    t = badge.ticks - _start
    p = min(1.0, t / DURATION)

    if badge.pressed():
        return True

    FADE = 900
    # cosmic hero image, fading in from black over the first ~900ms
    screen.blit(boot, vec2(0, 0))
    if t < FADE:
        screen.pen = color.rgb(0, 0, 0, int(255 * (1 - t / FADE)))
        screen.shape(shape.rectangle(0, 0, 160, 120))

    # loading bar ON TOP of the fade, its green fading in step with the hero
    ba = min(255, int(255 * t / FADE)) if t < FADE else 255
    screen.pen = color.rgb(34, 44, 54, ba)            # track
    screen.shape(shape.rounded_rectangle(BX, BY, BW, BH, 2))
    fillp = min(1.0, t / (DURATION - 250))
    fw = int(BW * fillp)
    if fw > 0:
        screen.pen = color.rgb(63, 185, 80, ba)       # neon green fill
        screen.shape(shape.rounded_rectangle(BX, BY, max(4, fw), BH, 2))
        screen.pen = color.rgb(235, 245, 255, ba)     # bright leading edge
        screen.shape(shape.rectangle(BX + max(4, fw) - 2, BY, 2, BH))

    # rear case lights ramp up with the boot
    badge.caselights(p * 0.5)

    if t >= DURATION:
        return True
    return None


run(update)
badge.caselights(0)
