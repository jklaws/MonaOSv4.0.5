# Safe, atomic filesystem writes for the badge's config files.
#
# Why: the badge's littlefs has wiped itself when writes were interrupted. A
# plain `with open(path,"w")` flushes on close, but it TRUNCATES the real file
# first — if power is lost or the device resets between truncate and flush, the
# critical file (secrets.py / settings.json / wifi.json) is left empty or
# partial. Writing to a temp file and renaming over the target is atomic on
# littlefs: the original stays intact until the fully-written temp replaces it,
# so an interrupted write can never destroy the existing file.
import os


def write_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.rename(tmp, path)            # atomic replace


def write_json(path, obj):
    import json
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.rename(tmp, path)


def read_text(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def read_json(path, default=None):
    import json
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:               # missing OR corrupt/partial file
        return {} if default is None else default
