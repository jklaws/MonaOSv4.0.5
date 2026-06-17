import sys
import os

sys.path.insert(0, "/system/apps/gallery")
os.chdir("/system/apps/gallery")

import math
import gc
import badgeware  # noqa: F401  (builtins: screen, color, shape, image, vec2, rect, pixel_font, SpriteSheet, badge, run)


def _scale_blit(img, x, y, w, h):
    dx, dy = x, y
    if w < 0: dx = x + w; w = -w
    if h < 0: dy = y + h; h = -h
    if w < 1: w = 1
    if h < 1: h = 1
    screen.blit(img, rect(int(dx), int(dy), int(w), int(h)))


# Allocate the big reused image buffer FIRST, while the heap is freshest, so a
# contiguous 160x120 (76KB) block is available even if a prior app (WiFi/badge)
# left the heap fragmented. The smaller sprite/thumbnails then fill in around it.
gc.collect()
img = image(160, 120)

screen.font = pixel_font.load("/system/assets/fonts/nope.ppf")
screen.antialias = X2

ui_hidden = False

# discover images + load thumbnails together, tolerant of a missing dir,
# missing/corrupt thumbnails, or dotless filenames (FS may be damaged)
files = []
thumbnails = []
try:
    entries = os.listdir("images")
except Exception:
    entries = []
for file in entries:
    file = file.rsplit("/", 1)[-1]
    if "." not in file:
        continue
    name, ext = file.rsplit(".", 1)
    if ext not in ("png", "jpg", "jpeg"):
        continue
    try:
        th = image.load(f"thumbnails/{file}")
    except Exception:
        th = None                       # keep index aligned with files
    files.append({"name": file, "title": name.replace("-", " ")})
    thumbnails.append(th)
gc.collect()

# given a gallery image index it clamps it into the range of available images


def clamp_index(index):
    return index % len(files) if files else 0

# load the main image based on the gallery index provided


# 'img' (the reused full-size buffer) is allocated at the top of the module.
# load_into() decodes each image into it, so scrolling never allocates a fresh
# 160x120 image and the heap can't fragment on the JPEG.


def load_image(index):
    if not files:
        return
    index = clamp_index(index)
    try:
        img.load_into(f"images/{files[index]['name']}")
    except Exception as e:  # noqa: BLE001
        # never let one bad/oversized image freeze scrolling; keep the last frame
        print("gallery: could not load", files[index]["name"], e)

# render the thumbnail strip


def draw_thumbnails():
    if ui_hidden:
        return

    spacing = 36
    # render the thumbnail strip
    for i in range(-3, 4):
        offset = thumbnail_scroll - int(thumbnail_scroll)

        pos = (((i + -offset) * spacing) + 60, 92)

        # determine which gallery image we're drawing the thumbnail for
        thumbnail = clamp_index(int(thumbnail_scroll) + i)
        thumbnail_image = thumbnails[thumbnail]
        if thumbnail_image is None:        # missing/corrupt thumbnail
            continue

        # draw the thumbnail shadow
        screen.pen = color.rgb(0, 0, 0, 50)
        screen.shape(shape.rectangle(
            pos[0] + 2, pos[1] + 2, thumbnail_image.width, thumbnail_image.height))

        # draw the active thumbnail outline
        if i == 0:
            brightness = (math.sin(badge.ticks / 200) * 127) + 127
            screen.pen = color.rgb(
                int(brightness), int(brightness), int(brightness), 150)
            screen.shape(shape.rectangle(
                pos[0] - 1, pos[1] - 1, thumbnail_image.width + 2, thumbnail_image.height + 2))

        screen.blit(thumbnail_image, vec2(pos[0], pos[1]))


# start up with the first image in the gallery
index = 0
load_image(index)

thumbnail_scroll = index
image_changed_at = None


def update():
    global index, thumbnail_scroll, ui_hidden, image_changed_at

    if not files:                       # empty / missing images dir
        screen.pen = color.rgb(13, 17, 23)
        screen.shape(shape.rectangle(0, 0, 160, 120))
        screen.pen = color.rgb(180, 190, 200)
        msg = "No images"
        w, _ = screen.measure_text(msg)
        screen.text(msg, int(80 - w / 2), 56)
        return None

    # if the user presses left or right then switch image
    if badge.pressed(BUTTON_A):
        index -= 1
        ui_hidden = False
        image_changed_at = badge.ticks
        load_image(index)

    if badge.pressed(BUTTON_C):
        index += 1
        ui_hidden = False
        image_changed_at = badge.ticks
        load_image(index)

    if badge.pressed(BUTTON_B):
        ui_hidden = not ui_hidden
        image_changed_at = badge.ticks

    if image_changed_at and (badge.ticks - image_changed_at) > 2000:
        ui_hidden = True

    # draw the currently selected image
    screen.blit(img, vec2(0, 0))

    # smooth scroll towards the newly selected image
    if thumbnail_scroll < index:
        thumbnail_scroll = min(thumbnail_scroll + 0.1, index)
    if thumbnail_scroll > index:
        thumbnail_scroll = max(thumbnail_scroll - 0.1, index)

    # draw the thumbnail ui
    draw_thumbnails()

    title = files[clamp_index(index)]["title"]
    width, _ = screen.measure_text(title)

    if not ui_hidden:
        screen.pen = color.rgb(0, 0, 0, 100)
        screen.shape(shape.rounded_rectangle(
            80 - (width / 2) - 8, -6, width + 16, 22, 6))
        screen.text(title, int(80 - (width / 2) + 1), 1)
        screen.pen = color.rgb(255, 255, 255)
        screen.text(title, int(80 - (width / 2)), 0)


# v2.0.2 launch() contract: apps run at import. No init()/on_exit() needed;
# run(update) loops until HOME.
run(update)
