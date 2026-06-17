#!/usr/bin/env python3
"""Headless badge-app runner built on badger/home's badge_simulator engine.

Adapts the 2026 firmware's `badgeware` API (bare-name builtins: screen, color,
shape, image, pixel_font, badge, vec2, rect, mat3, OFF/X2/X4, BUTTON_*, State,
display, run, machine, /system path-imports) onto the simulator's Pygame engine,
runs an app for N frames (with optional scripted input + forced state), and saves
a native 160x120 PNG. No window / keypress needed.

Usage:
  sim_run.py <app|path> [--frames N] [--out PNG] [--keys "5:A,30:UP+A"]
             [--set "state=GS.SELECT"] [--dt MS] [--root SYSTEM_DIR]
"""
import os, sys, argparse, importlib.util, types, re

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system")
SIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "badge_simulator.py")

ap = argparse.ArgumentParser()
ap.add_argument("app")
ap.add_argument("--root", default=FW)
ap.add_argument("--frames", type=int, default=20)
ap.add_argument("--out", default="/tmp/sim.png")
ap.add_argument("--scale", type=int, default=1)
ap.add_argument("--keys", default="")          # "5:A,30:UP+A"  frame -> buttons that frame
ap.add_argument("--set", default="")            # "state=GS.SELECT;cam=1000.0" forced after load
ap.add_argument("--dt", type=int, default=33)   # ms per simulated frame
ap.add_argument("--gui", action="store_true", help="interactive window (real-time + keyboard) instead of headless PNG")
args = ap.parse_args()
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
if not args.gui:
    os.environ["SDL_VIDEODRIVER"] = "dummy"   # headless render; GUI uses the real display
elif args.scale == 1:
    args.scale = 5                            # bigger default window for the GUI

# ---- import the engine (installs /system path remap at import time) ----------
spec = importlib.util.spec_from_file_location("badge_simulator", SIM)
bs = importlib.util.module_from_spec(spec); sys.modules["badge_simulator"] = bs
spec.loader.exec_module(bs)
bs.SIM_ROOT = os.path.abspath(args.root)
bs._perf_monitor = None
import urllib.request as _urlreq
bs._real_urllib_request = _urlreq   # the sim's urlopen mock proxies real HTTP through this

# Sandbox ALL device paths (the stock sim only mapped /system + simple root files,
# leaving /state/<sub> and /settings.json pointing at the unwritable host root).
import tempfile
_SANDBOX = os.path.join(tempfile.gettempdir(), "badge_sim_root")
_orig_map = bs.map_system_path
def _map(p):
    if isinstance(p, str) and p.startswith("/") and not p.startswith("/system"):
        dest = os.path.join(_SANDBOX, p.lstrip("/"))
        d = os.path.dirname(dest)
        if d:
            os.makedirs(d, exist_ok=True)
        return dest
    return _orig_map(p)
bs.map_system_path = _map

# fsutil's atomic write does os.rename(tmp, path) on device paths, which the stock
# sim doesn't remap. Remap rename/replace for device paths (host paths untouched).
_DEV = ("/state", "/settings", "/secrets", "/system", "/user_", "/contrib_", "/avatar")
def _devmap(p):
    return _map(p) if (isinstance(p, str) and any(p.startswith(x) for x in _DEV)) else p
_o_rename = os.rename
os.rename = lambda a, b, *r, **k: _o_rename(_devmap(a), _devmap(b), *r, **k)
if hasattr(os, "replace"):
    _o_replace = os.replace
    os.replace = lambda a, b, *r, **k: _o_replace(_devmap(a), _devmap(b), *r, **k)
# the sim's open only maps /system + simple root files; map device subdir paths
# (e.g. /state/x.json.tmp, /settings.json) via our sandbox before delegating.
import builtins as _B
_safe_open = _B.open
def _open(file, *a, **k):
    if isinstance(file, str) and any(file.startswith(x) for x in _DEV):
        file = _map(file)
    return _safe_open(file, *a, **k)
_B.open = _open
def _exists(p):
    try:
        return os.path.exists(_devmap(p))
    except Exception:
        return False
bs.file_exists = _exists

import pygame
pygame.init(); pygame.font.init()

# ---- REAL .ppf font rendering -------------------------------------------------
# The stock sim falls back to a generic TTF for every font, so it can't validate
# a font change (true glyph widths, the 8/11px size step). We decode the actual
# 1-bit .ppf with the firmware-matched codec (ppf.py) and rasterize glyphs, so
# screen.text / measure_text behave like the device. Falls back to the generic
# font if a file won't decode.
import ppf as _ppf

class _PpfFont:
    # Advance rules copied verbatim from firmware pixel_font.cpp measure()/render():
    #   space (0x20):  caret.x += glyph_width / 3     (font-wide max width, int div)
    #   any other char: caret.x += glyph->width + 1
    def __init__(self, decoded, name):
        self.name = name
        self.height = decoded["height"]
        self._gw = decoded["glyph_width"]          # font-wide max width
        self._space = self._gw // 3                 # firmware's space advance
        self._glyphs = {cp: (w, rows) for (cp, w, rows) in decoded["glyphs"]}

    def _adv(self, cp):
        if cp == 0x20:
            return self._space
        g = self._glyphs.get(cp)
        return (g[0] + 1) if g else self._space

    def size(self, text):
        text = str(text)
        return (sum(self._adv(ord(c)) for c in text), self.height)

    def get_height(self):
        return self.height

    def render(self, text, antialias=True, color=(255, 255, 255), *a, **k):
        text = str(text)
        w, h = self.size(text)
        surf = pygame.Surface((max(1, w), h), pygame.SRCALPHA)
        col = tuple(color[:4]) if len(color) >= 3 else (255, 255, 255)
        x = 0
        for ch in text:
            cp = ord(ch)
            if cp == 0x20:
                x += self._space
                continue
            g = self._glyphs.get(cp)
            if g is None:
                x += self._space
                continue
            gw, rows = g
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    if bit:
                        surf.set_at((x + rx, ry), col)
            x += gw + 1
        return surf

    def __getattr__(self, item):   # tolerate the wrapper's incidental attr reads
        raise AttributeError(item)

_orig_pf_load = bs.PixelFont.load
def _ppf_load(path, size=14):
    try:
        with open(bs.map_system_path(path), "rb") as f:
            decoded = _ppf.decode(f.read())
        name = decoded.get("name") or path.rsplit("/", 1)[-1]
        return _PpfFont(decoded, name)
    except Exception:
        return _orig_pf_load(path, size)
bs.PixelFont.load = staticmethod(_ppf_load)

# MicroPython time shims (ghbadge / sync.py use time.ticks_ms / sleep_ms / ...)
import time as _t
if not hasattr(_t, "ticks_ms"):
    _t.ticks_ms = lambda: int(_t.time() * 1000) & 0x3FFFFFFF
    _t.ticks_us = lambda: int(_t.time() * 1e6) & 0x3FFFFFFF
    _t.ticks_diff = lambda a, b: a - b
    _t.ticks_add = lambda a, b: a + b
    _t.sleep_ms = lambda ms: _t.sleep(ms / 1000.0)
    _t.sleep_us = lambda us: _t.sleep(us / 1e6)
bs.screen = bs.Screen(scale=args.scale); bs.io = bs.IO(); bs._io_ref = bs.io
screen, io = bs.screen, bs.io

# ---- patch the draw base for OUR API (pen / shape() / blit(img,pos) / clip) --
ST = bs._SurfaceTarget
ST.pen = property(lambda s: s.brush, lambda s, c: setattr(s, "brush", c))
ST.shape = lambda s, sh: bs._render_shape(s._surface, s._norm_color(s.brush), sh, getattr(sh, "transform", None))
_orig_blit = ST.blit
def _blit(self, image, pos, transform=None):
    if hasattr(pos, "w") and hasattr(pos, "h"):
        self.scale_blit(image, pos.x, pos.y, pos.w, pos.h, transform)
    elif hasattr(pos, "x"):
        _orig_blit(self, image, pos.x, pos.y, transform)
    else:
        _orig_blit(self, image, pos[0], pos[1], transform)
ST.blit = _blit
def _clip_set(self, r):
    self._surface.set_clip(None if r is None else pygame.Rect(int(r.x), int(r.y), int(r.w), int(r.h)))
ST.clip = property(lambda s: s._surface.get_clip(), _clip_set)
ST.raw = property(lambda s: pygame.image.tobytes(s._surface, "RGBA"))

# _Window (clipped sub-surface) is a separate class — give it the same API
W = bs._Window
W.pen = property(lambda s: s.brush, lambda s, c: setattr(s, "brush", c))
def _wshape(self, sh):
    clip = self._set_clip()
    try:
        bs._render_shape(self._parent._surface, self._parent._norm_color(self.brush),
                         sh, getattr(sh, "transform", None), offset=(self.x, self.y))
    finally:
        self._restore_clip(clip)
W.shape = _wshape
_worig = W.blit
def _wblit(self, image, pos, transform=None):
    if hasattr(pos, "w") and hasattr(pos, "h"):
        self.scale_blit(image, pos.x, pos.y, pos.w, pos.h, transform)
    elif hasattr(pos, "x"):
        _worig(self, image, pos.x, pos.y, transform)
    else:
        _worig(self, image, pos[0], pos[1], transform)
W.blit = _wblit

# ---- our badgeware API objects ---------------------------------------------
class _Color:
    rgb = staticmethod(bs.brushes.color)
    @staticmethod
    def hsv(h, s=1, v=1, a=255): return bs.brushes.color(v * 255, v * 255, v * 255, a)
class Vec2:
    __slots__ = ("x", "y")
    def __init__(self, x=0, y=0): self.x, self.y = x, y
    def __getitem__(self, i): return (self.x, self.y)[i]
class Rect:
    __slots__ = ("x", "y", "w", "h")
    def __init__(self, x, y, w, h): self.x, self.y, self.w, self.h = x, y, w, h
class _RomFont:
    _c = {}
    def __getattr__(self, n):
        if n not in self._c:
            self._c[n] = bs.PixelFont.load("/system/assets/fonts/%s.ppf" % n)
        return self._c[n]
class Badge:
    def __init__(self, io): self._io = io
    # b=None matches the real API's "any key" form (e.g. startup's press-to-skip)
    def pressed(self, b=None): return bool(self._io.pressed) if b is None else (b in self._io.pressed)
    def held(self, b=None): return bool(self._io.held) if b is None else (b in self._io.held)
    def released(self, b=None): return bool(self._io.released) if b is None else (b in self._io.released)
    def changed(self, b=None):
        if b is None: return bool(self._io.pressed or self._io.released)
        return b in self._io.pressed or b in self._io.released
    @property
    def ticks(self): return self._io.ticks
    @property
    def ticks_delta(self): return self._io.ticks_delta
    def clear(self): self._io.pressed.clear()
    def poll(self): pass
    def caselights(self, *a, **k): pass
badge = Badge(io)

def _mk(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items(): setattr(m, k, v)
    sys.modules[name] = m
    return m
_mk("machine", unique_id=lambda: b'\xf0\x54\xb0\x9a\xa7\x85\x38\xd4', reset=lambda: None)
_mk("secrets", GITHUB_USERNAME="octocat", WIFI_SSID="sim", WIFI_PASSWORD="", GITHUB_TOKEN="")
class _WLAN:   # instant-connect (the sim's mock has a 1.5s delay that stalls headless)
    def __init__(self, *a, **k): pass
    def active(self, *a): return True
    def isconnected(self): return True
    def connect(self, *a, **k): pass
    def disconnect(self, *a, **k): pass
    def scan(self): return [(b"sim", b"", 1, -45, 0, 0)]
    def status(self, *a): return 3
    def config(self, *a, **k): return "sim"
    def ifconfig(self, *a): return ("192.168.1.50", "255.255.255.0", "192.168.1.1", "8.8.8.8")
_mk("network", WLAN=_WLAN, STA_IF=0, AP_IF=1)
_ureq = _mk("urllib.urequest", urlopen=bs._MockUrequest.urlopen)
_mk("urllib", urequest=_ureq); sys.modules["urequest"] = _ureq

_cap = {}
if args.gui:
    run = bs.run                              # the simulator's real interactive loop
else:
    def run(fn=None, *a, **k):
        _cap["u"] = fn
        return type("R", (), {"result": None})()
disp = types.SimpleNamespace(update=lambda *a, **k: None)

bw = types.ModuleType("badgeware")
for k, v in dict(screen=screen, display=disp, run=run, State=bs.State, image=bs.Image,
                 Image=bs.Image, SpriteSheet=bs.SpriteSheet, Animation=bs.Animation,
                 color=_Color, shape=bs.shapes, pixel_font=bs.PixelFont, rom_font=_RomFont(),
                 badge=badge, vec2=Vec2, rect=Rect, mat3=bs.Matrix, X2=bs.Image.X2,
                 X4=bs.Image.X4, OFF=bs.Image.OFF, clamp=bs.clamp,
                 BUTTON_A=bs.IO.BUTTON_A, BUTTON_B=bs.IO.BUTTON_B, BUTTON_C=bs.IO.BUTTON_C,
                 BUTTON_UP=bs.IO.BUTTON_UP, BUTTON_DOWN=bs.IO.BUTTON_DOWN,
                 BUTTON_HOME=bs.IO.BUTTON_HOME).items():
    setattr(bw, k, v)
sys.modules["badgeware"] = bw
_mk("badgeware.math", clamp=bs.clamp); bw.math = sys.modules["badgeware.math"]
_mk("badgeware.filesystem", file_exists=bs.file_exists, is_dir=bs.is_dir); bw.filesystem = sys.modules["badgeware.filesystem"]

import builtins as B
for k in ("screen", "display", "run", "image", "SpriteSheet", "color", "shape",
          "pixel_font", "rom_font", "badge", "vec2", "rect", "mat3", "X2", "X4", "OFF",
          "State", "BUTTON_A", "BUTTON_B", "BUTTON_C", "BUTTON_UP", "BUTTON_DOWN", "BUTTON_HOME"):
    setattr(B, k, getattr(bw, k))

# /system path-imports:  __import__("/system/ghbadge")
_real_import = B.__import__
_pm = {}
def _imp(name, *a, **k):
    if isinstance(name, str) and name.startswith("/"):
        if name in _pm: return _pm[name]
        p = bs.map_system_path(name)
        if not p.endswith(".py"): p += ".py"
        s = importlib.util.spec_from_file_location(name.strip("/").replace("/", "_"), p)
        m = importlib.util.module_from_spec(s); _pm[name] = m; s.loader.exec_module(m)
        return m
    return _real_import(name, *a, **k)
B.__import__ = _imp

# ---- load the app -----------------------------------------------------------
app = args.app
if not app.endswith(".py"):
    app = os.path.join(bs.SIM_ROOT, "apps", app, "__init__.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(app)))   # sibling imports (ui, mona, ...)
src = open(app).read()
ns = {"__name__": "__sim_app__"}
exec(compile(src, app, "exec"), ns)
if args.gui:
    sys.exit(0)   # in GUI mode the app's run(update) entered the interactive loop above
u = _cap.get("u") or ns.get("update")
if u is None:
    print("ERROR: no update() captured"); sys.exit(1)

# forced globals (e.g. state=GS.SELECT)
if args.set:
    for a in args.set.split(";"):
        if not a.strip(): continue
        key, val = a.split("=", 1)
        ns[key.strip()] = eval(val.strip(), ns)

# scripted input: frame -> buttons
keymap = {}
for part in filter(None, args.keys.split(",")):
    f, btns = part.split(":")
    keymap[int(f)] = ["BUTTON_" + b for b in btns.split("+")]

io.ticks = 0; io._last_ticks = 0
for f in range(args.frames):
    io.ticks = f * args.dt
    io.ticks_delta = args.dt
    io.pressed = set(keymap.get(f, []))
    io.held = set(io.pressed)
    try:
        u()
    except Exception as e:
        import traceback; traceback.print_exc()
        print("FRAME-ERR at", f, repr(e)); break

pygame.image.save(screen._surface, args.out)
print("SAVED", args.out, screen._surface.get_size())
