# Reusable on-screen keyboard for the 160x120 badge. Host app: create a Keyboard,
# call kb.update() each frame, and when kb.done is True read kb.text. HOME (wired
# by the launcher) exits/cancels. Uses the case-distinguishing 'nope' font so
# upper/lowercase are readable; chrome uses the compact 'ark'.
#   import:  Keyboard = __import__("/system/keyboard").Keyboard
import badgeware  # noqa: F401  (builtins: screen, color, shape, pixel_font, badge, BUTTON_*)

_small = pixel_font.load("/system/assets/fonts/nope.ppf")
_chrome = pixel_font.load("/system/assets/fonts/ark.ppf")

BG = color.rgb(24, 26, 30)
PANEL = color.rgb(40, 44, 52)
HILITE = color.rgb(211, 250, 55)
HITEXT = color.rgb(20, 24, 16)
WHITE = color.rgb(235, 245, 255)
FADED = color.rgb(235, 245, 255, 110)
ON_COLOR = color.rgb(235, 150, 40)

LOWER = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
UPPER = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
SYMBOLS = ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\".,/?\\|~`"]
ALABEL = {"shift": "Aa", "space": "spc", "sym": "#%", "show": "eye", "del": "del", "ok": "OK"}


class Keyboard:
    def __init__(self, title, text="", mask=False):
        self.title = title
        self.text = text
        self.mask = mask
        self.show = not mask
        self.shift = False
        self.syms = False
        self.kr = 0
        self.kc = 0
        self.done = False
        # password fields get a show/hide toggle; plain fields don't need it
        self.actions = (["shift", "space", "sym", "show", "del", "ok"] if mask
                        else ["shift", "space", "sym", "del", "ok"])

    def _rows(self):
        return SYMBOLS if self.syms else (UPPER if self.shift else LOWER)

    def _cols(self):
        g = self._rows()
        return len(g[self.kr]) if self.kr < len(g) else len(self.actions)

    def _activate(self):
        g = self._rows()
        if self.kr < len(g):
            self.text += g[self.kr][self.kc]
            if self.shift:
                self.shift = False
            return
        a = self.actions[self.kc]
        if a == "shift":
            self.shift = not self.shift
        elif a == "space":
            self.text += " "
        elif a == "sym":
            self.syms = not self.syms
            self.kr = min(self.kr, len(self._rows()))
        elif a == "show":
            self.show = not self.show
        elif a == "del":
            self.text = self.text[:-1]
        elif a == "ok":
            self.done = True

    def update(self):
        if badge.pressed(BUTTON_UP):
            self.kr = (self.kr - 1) % (len(self._rows()) + 1)
            self.kc = min(self.kc, self._cols() - 1)
        if badge.pressed(BUTTON_DOWN):
            self.kr = (self.kr + 1) % (len(self._rows()) + 1)
            self.kc = min(self.kc, self._cols() - 1)
        if badge.pressed(BUTTON_A):
            self.kc = (self.kc - 1) % self._cols()
        if badge.pressed(BUTTON_C):
            self.kc = (self.kc + 1) % self._cols()
        if badge.pressed(BUTTON_B):
            self._activate()
        self._draw()

    def _draw(self):
        screen.pen = BG
        screen.shape(shape.rectangle(0, 0, 160, 120))
        # header
        screen.pen = PANEL
        screen.shape(shape.rectangle(0, 0, 160, 13))
        screen.font = _chrome
        screen.pen = WHITE
        t = self.title if len(self.title) <= 24 else self.title[:23] + "…"
        screen.text(t, 4, 3)
        # text field + mode badge
        screen.font = _small
        screen.pen = PANEL
        screen.shape(shape.rounded_rectangle(3, 16, 154, 14, 3))
        shown = self.text if self.show else ("*" * len(self.text))
        if len(shown) > 18:
            shown = "…" + shown[-17:]
        screen.pen = WHITE
        screen.text(shown + "_", 7, 18)
        mode = "#%" if self.syms else ("ABC" if self.shift else "abc")
        screen.pen = ON_COLOR if (self.shift or self.syms) else FADED
        mw, _ = screen.measure_text(mode)
        screen.text(mode, 152 - mw, 18)
        # key grid
        grid = self._rows()
        y0, pitch, keyh = 32, 17, 14
        for r, line in enumerate(grid):
            cw = 152 / len(line)
            for c in range(len(line)):
                x = 4 + c * cw
                y = y0 + r * pitch
                active = (self.kr == r and self.kc == c)
                screen.pen = HILITE if active else PANEL
                screen.shape(shape.rounded_rectangle(int(x), y, int(cw) - 1, keyh, 2))
                screen.pen = HITEXT if active else WHITE
                ch = line[c]
                w, _ = screen.measure_text(ch)
                screen.text(ch, int(x + (cw - w) / 2), y + 1)
        # action row
        ar = len(grid)
        y = y0 + ar * pitch
        cw = 152 / len(self.actions)
        for c in range(len(self.actions)):
            x = 4 + c * cw
            active = (self.kr == ar and self.kc == c)
            act = self.actions[c]
            on = ((act == "shift" and self.shift) or (act == "sym" and self.syms)
                  or (act == "show" and self.show))
            screen.pen = HILITE if active else (ON_COLOR if on else color.rgb(60, 66, 76))
            screen.shape(shape.rounded_rectangle(int(x), y, int(cw) - 1, keyh + 1, 2))
            screen.pen = HITEXT if (active or on) else WHITE
            lbl = ALABEL[act]
            if act == "shift" and self.shift:
                lbl = "aA"
            if act == "sym" and self.syms:
                lbl = "ab"
            if act == "show" and self.show:
                lbl = "hid"
            w, _ = screen.measure_text(lbl)
            screen.text(lbl, int(x + (cw - w) / 2), y + 1)
