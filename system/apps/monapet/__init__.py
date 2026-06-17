import sys
import os

sys.path.insert(0, "/system/apps/monapet")
os.chdir("/system/apps/monapet")


import ui
from mona import Mona
import math
# v2.0.2 port: io -> badge; run is a builtin; State from badgeware.
from badgeware import State

# v2.0.2 upgrade: smooth anti-aliased rendering (X2 ~ -7% FPS, well worth it)
screen.antialias = X2

mona = Mona(82)  # create mona!

# Decay rates now live in mona.py (DECAY) and run in REAL time -- Mona keeps
# living while the app/badge are off (caught up on load via Mona.apply_away()).


def game_update():
    global mona

    if not mona.is_dead():
        mona.tick(badge.ticks_delta / 1000)   # real-time decay while open

        # play with mona!
        if badge.pressed(BUTTON_A):
            mona.happy(28)
            mona.add_xp(3)
            mona.do_action("heart")

        # feed mona!
        if badge.pressed(BUTTON_B):
            mona.hunger(32)
            mona.add_xp(3)
            mona.do_action("eating")

        # clean mona!
        if badge.pressed(BUTTON_C):
            mona.clean(30)
            mona.add_xp(3)
            mona.do_action("dance")

        if mona.time_since_last_position_change() > 5:
            mona.move_to_random()

        if mona.time_since_last_mood_change() > 8:
            mona.random_idle()

        # worried look when a need is low OR Mona is getting sick
        if mona.is_sick() or min(mona.hunger(), mona.happy(), mona.clean()) < 30:
            mona.set_mood("notify")

    else:
        mona.set_mood("dead")
        mona.move_to_center()

        if badge.pressed(BUTTON_B):
            mona = Mona(82)


def _update_caselights():
    # v2.0.2 upgrade: rear 4-zone case lights reflect Mona's wellbeing
    if mona.is_dead():
        b = (math.sin(badge.ticks / 180) * 0.5 + 0.5) * 0.5  # urgent pulse
        badge.caselights(b, 0.0, 0.0, b)
    else:
        avg = (mona.happy() + mona.hunger() + mona.clean()) / 3
        pulse = math.sin(badge.ticks / 500) * 0.12 + 0.88
        b = (avg / 100) * 0.6 * pulse
        badge.caselights(b)


def update():
    game_update()
    mona.update()
    _update_caselights()
    ui.background(mona)
    mona.draw()

    if not mona.is_dead():
        ui.draw_bar("happy",  2, 41, mona.happy())
        ui.draw_bar("hunger", 2, 58, mona.hunger())
        ui.draw_bar("clean",  2, 75, mona.clean())

        ui.draw_button(4, 100,  "play", mona.current_action() == "heart")
        ui.draw_button(55, 100,  "feed", mona.current_action() == "eating")
        ui.draw_button(106, 100, "clean", mona.current_action() == "dance")
    else:
        ui.draw_button(55, 100, "reset", True)

    ui.draw_header(mona)


def init():
    state = {
        "happy": 100,
        "hunger": 100,
        "clean": 100,
    }
    if State.load("monapet", state):
        mona.load(state)

    del state


def on_exit():
    badge.caselights(0)  # turn off rear lights when leaving Mona
    State.save("monapet", mona.save())


# v2.0.2 launch() contract: apps run at import. init() loads saved state;
# run(update) loops until HOME, then launch() calls on_exit -> State.save.
init()
run(update)
