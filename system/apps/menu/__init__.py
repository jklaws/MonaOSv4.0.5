import sys
import os

sys.path.insert(0, "/system/apps/menu")
sys.path.insert(0, "/")
os.chdir("/system/apps/menu")

import math
import badgeware  # noqa: F401  (builtins: screen, color, shape, image, SpriteSheet, badge, rom_font, run)
screen.antialias = X2  # v2.0.2 upgrade: smooth anti-aliased rendering
from badgeware.filesystem import is_dir, file_exists
from icon import Icon
import ui

APPS_ROOT = "/system/apps"

screen.font = rom_font.ark

# Auto-discover apps with __init__.py
apps = []
try:
    for entry in os.listdir(APPS_ROOT):
        app_path = f"{APPS_ROOT}/{entry}"
        if is_dir(app_path) and file_exists(f"{app_path}/__init__.py"):
            if entry not in ("menu", "startup"):
                # optional display label override: <app>/name.txt
                label = entry
                if file_exists(f"{app_path}/name.txt"):
                    try:
                        with open(f"{app_path}/name.txt") as nf:
                            label = nf.read().strip() or entry
                    except Exception:
                        pass
                apps.append((label, entry))
except Exception as e:
    print("Error discovering apps:", e)

# --- app ordering -----------------------------------------------------------
# Alphabetical by the display label, then float Setup to the FIRST slot on a
# fresh/unconfigured device (so a first-time user lands straight on it) and sink
# it to the LAST slot once Wi-Fi has been configured (it's then rarely needed).
def _is_configured():
    # configured == Setup has written a non-empty WIFI_SSID to /secrets.py.
    # Read it textually (don't `import secrets` — a malformed file would crash).
    try:
        with open("/secrets.py") as f:
            for ln in f:
                s = ln.strip()
                if s.startswith("WIFI_SSID"):
                    return bool(s.split("=", 1)[1].strip().strip("'\""))
    except Exception:
        pass
    return False


apps.sort(key=lambda a: a[0].lower())   # alphabetical by display name
_setup = next((a for a in apps if a[1] == "setup"), None)
if _setup:
    apps.remove(_setup)
    apps.append(_setup) if _is_configured() else apps.insert(0, _setup)

# Pagination
APPS_PER_PAGE = 6
current_page = 0
total_pages = max(1, math.ceil(len(apps) / APPS_PER_PAGE))


def load_page_icons(page):
    icons = []
    start_idx = page * APPS_PER_PAGE
    end_idx = min(start_idx + APPS_PER_PAGE, len(apps))
    for i in range(start_idx, end_idx):
        name, path = apps[i]
        icon_idx = i - start_idx
        x = icon_idx % 3
        y = math.floor(icon_idx / 3)
        pos = (x * 48 + 33, y * 48 + 42)
        try:
            icon_path = f"{APPS_ROOT}/{path}/icon.png"
            if not file_exists(icon_path):
                icon_path = "/system/apps/menu/default_icon.png"
            sprite = image.load(icon_path)
            icons.append(Icon(pos, name, icon_idx % APPS_PER_PAGE, sprite))
        except Exception as e:
            print("Error loading icon for", path, e)
    return icons


icons = load_page_icons(current_page)
active = 0
MAX_ALPHA = 255
alpha = 30


def update():
    global active, icons, alpha, current_page, total_pages

    if badge.pressed(BUTTON_C):
        active += 1
    if badge.pressed(BUTTON_A):
        active -= 1
    if badge.pressed(BUTTON_UP):
        active -= 3
    if badge.pressed(BUTTON_DOWN):
        active += 3

    if active >= len(icons):
        if current_page < total_pages - 1:
            current_page += 1
            icons = load_page_icons(current_page)
            active = 0
        else:
            active = 0
    elif active < 0:
        if current_page > 0:
            current_page -= 1
            icons = load_page_icons(current_page)
            active = len(icons) - 1
        else:
            active = len(icons) - 1

    if badge.pressed(BUTTON_B):
        app_idx = current_page * APPS_PER_PAGE + active
        if app_idx < len(apps):
            app_path = f"{APPS_ROOT}/{apps[app_idx][1]}"
            if is_dir(app_path) and file_exists(f"{app_path}/__init__.py"):
                return app_path

    ui.draw_background()
    ui.draw_header()

    for i in range(len(icons)):
        icons[i].activate(active == i)
        icons[i].draw()

    if Icon.active_icon:
        label = Icon.active_icon.name
        w, _ = screen.measure_text(label)
        screen.pen = color.rgb(211, 250, 55)
        screen.shape(shape.rounded_rectangle(80 - (w / 2) - 4, 100, w + 8, 15, 4))
        screen.pen = color.rgb(0, 0, 0, 150)
        screen.text(label, int(80 - (w / 2)), 101)

    # page indicator (matches the Tufty menu): one pip per app, grouped into
    # 3x2 page-blocks on the right edge, vertically centred, current app brightest
    if total_pages > 1:
        active_index = current_page * APPS_PER_PAGE + active
        px = 150
        py = 65 - (total_pages * 7) / 2
        for page in range(total_pages):
            offset = page * APPS_PER_PAGE
            pips = min(APPS_PER_PAGE, len(apps) - offset)
            for pip in range(pips):
                if active_index - (page * APPS_PER_PAGE) == pip:
                    screen.pen = color.rgb(255, 255, 255, 200)
                elif page == current_page:
                    screen.pen = color.rgb(255, 255, 255, 100)
                else:
                    screen.pen = color.rgb(255, 255, 255, 50)
                screen.put(int(px + (pip % 3) * 2), int(py + page * 7 + (pip // 3) * 2))

    if alpha <= MAX_ALPHA:
        screen.pen = color.rgb(0, 0, 0, 255 - alpha)
        screen.clear()
        alpha += 30

    return None


# v2.0.2 launcher contract: run the loop; its result (the selected app path)
# becomes on_exit, which launch() returns verbatim.
on_exit = run(update).result
