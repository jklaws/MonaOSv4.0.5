import sys
import os

sys.path.insert(0, "/system/apps/monapet")
os.chdir("/system/apps/monapet")

# v2.0.2 port: badgeware is now a package that injects builtins
# (screen, color, shape, rect, vec2, SpriteSheet, badge, ...). Importing it
# ensures those globals exist; clamp moved to badgeware.math.
import badgeware  # noqa: F401
from badgeware.math import clamp
import random
import math
import time
import gc


def _now():
    # real-time epoch seconds from the RTC; stable across reboots so Mona keeps
    # living while the app (and badge) are off. Falls back if time() is unset.
    try:
        return int(time.time())
    except Exception:
        return int(time.mktime(time.localtime()))


# seconds for a stat to fall 100 -> 0 in REAL time. Paced so the bars visibly
# drift within a sitting and create a real care loop (tend her every couple
# hours), while the health buffer below keeps a nap/overnight from being fatal.
DECAY = {"hunger": 7200, "happy": 10800, "clean": 14400}    # 2h / 3h / 4h
HEALTH_FALL = 28800     # ~8h with a need at zero before Mona dies (forgiving)
HEALTH_REGEN = 7200     # ~2h of good care restores full health
MAX_AWAY = 7 * 86400    # cap catch-up so a bad clock can't instantly kill Mona


def _scale_blit(img, x, y, w, h):
    # Port of old badgeware screen.scale_blit(img, x, y, w, h).
    # v2.0.2: blit(src, dest_rect) scales into the rect; a negative width/height
    # in the dest rect mirrors the sprite (restores Mona facing left + reflection).
    if -1 < w < 1:
        w = 1 if w >= 0 else -1
    if -1 < h < 1:
        h = 1 if h >= 0 else -1
    screen.blit(img, rect(int(x), int(y), int(w), int(h)))


class Mona:
  _moods = ["heart", "eating", "dance", "code", "default", "notify", "dead"]
  _frames = {"heart": 6, "eating": 6, "dance": 6, "code": 4,
             "default": 6, "notify": 4, "dead": 4}
  # Lazy sprite cache (Mona Noir pattern). Instead of holding all 7 sheets
  # (~161KB) we keep "default" pinned (idle + wall portrait) plus a tiny LRU of
  # recently shown animations, freeing the rest -> ~3 sheets (~50KB) resident.
  # Sheets only (re)load on a mood/action *transition*, never per frame.
  _cache = {}
  _lru = []
  _CAP = 2
  _PIN = "default"

  @staticmethod
  def anim(name):
    a = Mona._cache.get(name)
    if a is not None:
      if name != Mona._PIN:
        try:
          Mona._lru.remove(name)
        except ValueError:
          pass
        Mona._lru.append(name)
      return a
    a = SpriteSheet("/system/assets/mona-sprites/mona-%s.png" % name,
                    Mona._frames[name], 1).animation()
    Mona._cache[name] = a
    if name != Mona._PIN:
      Mona._lru.append(name)
      while len(Mona._lru) > Mona._CAP:
        Mona._cache.pop(Mona._lru.pop(0), None)
      gc.collect()
    return a

  def __init__(self, y):
    self._happy = 100
    self._hunger = 100
    self._clean = 100
    self._health = 100
    self._xp = 0.0
    self._born = _now()
    self._last_seen = _now()
    self._animation = None
    self._mood = None
    self._mood_changed_at = (badge.ticks / 1000)
    self._action = None
    self._action_changed_at = None
    self._position_changed_at = (badge.ticks / 1000)
    self._position = (80, y + 2)
    self._direction = 1
    self._target = 80
    self._speed = 0.5
    self.set_mood("default")

  def load(self, state):
    # default missing keys to healthy values so a partial/old save doesn't
    # resurrect Mona already dead. Old 1.x saves (no health/born) migrate cleanly.
    self._happy = state.get("happy", 100)
    self._hunger = state.get("hunger", 100)
    self._clean = state.get("clean", 100)
    self._health = state.get("health", 100)
    self._xp = state.get("xp", 0.0)
    self._born = state.get("born", _now())
    self._last_seen = state.get("last_seen", _now())
    self.apply_away()        # catch up the real time spent away

  def save(self):
    self._last_seen = _now()
    return {
      "happy": self._happy,
      "hunger": self._hunger,
      "clean": self._clean,
      "health": self._health,
      "xp": self._xp,
      "born": self._born,
      "last_seen": self._last_seen,
    }

  # ---- real-time stat model (Mona keeps living while you're away) -----------
  def _decay(self, secs):
    if secs <= 0:
      return
    self._hunger = clamp(self._hunger - secs * 100 / DECAY["hunger"], 0, 100)
    self._happy = clamp(self._happy - secs * 100 / DECAY["happy"], 0, 100)
    self._clean = clamp(self._clean - secs * 100 / DECAY["clean"], 0, 100)
    lo = min(self._hunger, self._happy, self._clean)
    if lo <= 0:                                   # a need at zero hurts health
      self._health = clamp(self._health - secs * 100 / HEALTH_FALL, 0, 100)
    elif lo > 40 and self._health < 100:          # well cared for -> recover
      self._health = clamp(self._health + secs * 100 / HEALTH_REGEN, 0, 100)
    self._xp += secs / 3600.0                     # +1 XP per real hour survived

  def apply_away(self):
    now = _now()
    elapsed = now - self._last_seen
    if elapsed < 0:
      elapsed = 0
    if elapsed > MAX_AWAY:
      elapsed = MAX_AWAY
    self._decay(elapsed)
    self._last_seen = now

  def tick(self, secs):
    self._decay(secs)                             # real-time decay while open

  def add_xp(self, amount):
    self._xp += amount

  def level(self):
    return 1 + int(self._xp // 100)

  def xp_into_level(self):
    return int(self._xp % 100)

  def age_days(self):
    return max(0, int((_now() - self._born) // 86400))

  def health(self):
    return int(self._health)

  def is_sick(self):
    return (not self.is_dead()) and self._health < 40

  def draw(self):
    x, y = self._position

    if self._action:
      action_time = (badge.ticks / 1000) - self._action_changed_at
      image = Mona.anim(self._action).frame(round(action_time * 10))
    else:
      image = Mona.anim(self._mood).frame(round(badge.ticks / 100))

    # 2.0: sprites are now authored at display size, so draw 1:1 (no upscale)
    width, height = image.width, image.height

    # draw monas shadow
    screen.pen = color.rgb(0, 0, 0, 20)
    screen.shape(shape.rectangle(x - (width / 2) + 5, y, width - 10, 2))
    screen.shape(shape.rectangle(x - (width / 2) + 5 + 2, y - 2, width - 10 - 4, 4))

    # invert mona if they are walking left
    width *= self._direction

    floating = math.sin(badge.ticks / 250) * 5 + 5 if self._mood == "dead" else 0

    x -= abs(width / 2)
    y -= height + floating

    alpha = 150 if self._mood == "dead" else 255
    image.alpha = alpha
    _scale_blit(image, x, y, width, height)

    # reflection
    image.alpha = int(alpha * 0.2)
    _scale_blit(image, x, self._position[1] + (floating / 2) + 1, width, -20)
    image.alpha = 255

  def move_to(self, target):
    self._target = target
    self._position_changed_at = (badge.ticks / 1000)

  def move_to_center(self):
    self._target = 80
    self._position_changed_at = (badge.ticks / 1000)

  def move_to_random(self):
    self.move_to(random.randint(90, 130))

  def time_since_last_position_change(self):
    return (badge.ticks / 1000) - self._position_changed_at

  def position(self):
    return self._position

  def set_mood(self, mood):
    self._mood = mood
    self._mood_changed_at = (badge.ticks / 1000)

  def do_action(self, action):
    self._action = action
    self._action_changed_at = (badge.ticks / 1000)

  def current_action(self):
    return self._action

  def is_dead(self):
    # 2.0: a need hitting zero no longer kills instantly -- it drains health, so
    # Mona gets sick first and you have hours to rescue her before she's gone.
    return self._health <= 0

  def happy(self, amount=0):
    self._happy = clamp(self._happy + amount, 0, 100)
    return self._happy

  def clean(self, amount=0):
    self._clean = clamp(self._clean + amount, 0, 100)
    return self._clean

  def hunger(self, amount=0):
    self._hunger = clamp(self._hunger + amount, 0, 100)
    return self._hunger

  def update(self):
    x, y = self._position

    if x != self._target and not self._action:
      self._direction = 1 if x > self._target else -1
      self._position = (x - (self._speed * self._direction), y)

    if self._action:
      if (badge.ticks / 1000) - self._action_changed_at > 2:
        self._action = None

  def random_idle(self):
    idles = ["code", "default", "heart", "dance"]
    self.set_mood(random.choice(idles))

  def time_since_last_mood_change(self):
    return (badge.ticks / 1000) - self._mood_changed_at


# preload + pin only the idle/portrait sheet; everything else loads on demand
Mona.anim("default")
