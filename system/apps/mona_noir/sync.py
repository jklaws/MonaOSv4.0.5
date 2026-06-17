# GitHub-backed sync for Mona Noir.
#
# REBOOT-SAFE CONTRACT: call sync()/fetch_global() synchronously from inside a
# single update() frame, AFTER drawing a "syncing" screen and calling
# display.update() once. Because the whole Wi-Fi connect + TLS + HTTP runs
# blocking inside that one frame, the framework's per-frame display.update()
# (the LCD parallel-DMA) never fires during the cyw43 association -- which is
# the collision that hard-reboots the badge. Keep it that way.
#
# Reads (global graph meter, leaderboard) are public and need no token.
# Writes (players/<handle>.json, breach issues) need a GITHUB_TOKEN in secrets
# with write access to the game repo; they fail gracefully without one.
import network
import json
import time
import machine
from urllib.urequest import urlopen

try:
    import ubinascii as binascii
except ImportError:
    import binascii

OWNER = ""   # owner of the shared Mona Noir leaderboard repo (optional)
REPO = "mona-noir"
RAW = "https://raw.githubusercontent.com/%s/%s/main/" % (OWNER, REPO)
API = "https://api.github.com/repos/%s/%s/" % (OWNER, REPO)
UA = "MonaNoirBadge"


def _secret(name, default=""):
    try:
        import secrets
        return getattr(secrets, name, default) or default
    except Exception:
        return default


def token():
    return _secret("GITHUB_TOKEN", "")


def handle():
    return _secret("GITHUB_USERNAME", "")


def wifi_connect(timeout=15):
    """Bring up STA and block until connected (or timeout). Returns wlan or None."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    ssid = _secret("WIFI_SSID")
    if not ssid:
        return None
    try:
        wlan.connect(ssid, _secret("WIFI_PASSWORD"))
    except Exception:
        try:
            wlan.connect(ssid, _secret("WIFI_PASSWORD"), security=0)
        except Exception:
            pass
    t = time.ticks_ms()
    while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), t) < timeout * 1000:
        time.sleep_ms(200)
    return wlan if wlan.isconnected() else None


def _read(resp, cap=60000):
    parts = []          # join once instead of O(n^2) byte concat per chunk
    total = 0
    buf = bytearray(512)
    while True:
        try:
            n = resp.readinto(buf)
        except Exception:
            break
        if not n:
            break
        parts.append(bytes(buf[:n]))
        total += n
        if total > cap:
            break
    return b"".join(parts)


def _req(url, method="GET", headers=None, body=None, auth=False):
    h = {"User-Agent": UA}
    if auth and token():
        h["Authorization"] = "Bearer " + token()
        h["Accept"] = "application/vnd.github+json"
    if headers:
        h.update(headers)
    resp = urlopen(url, data=body, method=method, headers=h)
    try:
        return _read(resp)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def fetch_global():
    """Public read: live Graph meter + leaderboard. No token required."""
    out = {"graph": None, "leaderboard": None}
    ts = time.ticks_ms()
    try:
        out["graph"] = json.loads(_req(RAW + "graph_state.json?t=%d" % ts))
    except Exception as e:
        print("graph fetch", e)
    try:
        out["leaderboard"] = json.loads(_req(RAW + "leaderboard.json?t=%d" % ts))
    except Exception as e:
        print("lb fetch", e)
    return out


def _dv(h, sc, nodes, pins):
    k = b""  # device-signing key omitted from the public source
    m = ("%s|%d|%s|%s" % (h, sc, ",".join(sorted(nodes)), ",".join(sorted(pins)))).encode()
    v = 0xcbf29ce484222325
    for b in k + machine.unique_id() + m:
        v ^= b
        v = (v * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return "%016x" % v


def _player_payload(state, h):
    nodes = list(state.get("restored", []))
    pins = list(state.get("pins", []))
    sc = int(state.get("score", 0))
    return {
        "player_id": h,
        "github_handle": h,
        "github_verified": bool(state.get("verified")),
        "score": sc,
        "nodes_restored": nodes,
        "pins": pins,
        "streak": int(state.get("streak", 0)),
        "last_sync": time.ticks_ms(),
        "device": "".join("%02x" % b for b in machine.unique_id()),
        "chk": _dv(h, sc, nodes, pins),
    }


def push_player(state):
    """Commit players/<handle>.json via the Contents API. Needs a write token."""
    h = handle()
    if not token() or not h:
        return False, "no token"
    path = "contents/players/%s.json" % h
    sha = None
    try:
        cur = json.loads(_req(API + path, auth=True))
        sha = cur.get("sha")
    except Exception:
        sha = None
    content = binascii.b2a_base64(json.dumps(_player_payload(state, h)).encode()).decode().strip()
    body = {"message": "sync: %s" % h, "content": content}
    if sha:
        body["sha"] = sha
    try:
        out = _req(API + path, method="PUT", body=json.dumps(body).encode(), auth=True)
        r = json.loads(out) if out else {}
        if "content" in r or "commit" in r:
            return True, "committed"
        return False, r.get("message", "rejected")
    except Exception as e:
        return False, str(e)


def open_breach(victim, pin_id):
    """PvP: open a BREACH issue (the live hack feed). Needs a write token."""
    h = handle()
    if not token() or not h or not victim:
        return False, "no token"
    body = {
        "title": "BREACH: @%s -> @%s (%s)" % (h, victim, pin_id),
        "body": "Mona Noir breach logged from a badge.\n- attacker: @%s\n- victim: @%s\n- pin: %s" % (h, victim, pin_id),
    }
    try:
        out = _req(API + "issues", method="POST", body=json.dumps(body).encode(), auth=True)
        r = json.loads(out) if out else {}
        return ("number" in r), r.get("html_url", r.get("message", "?"))
    except Exception as e:
        return False, str(e)


def sync(state, timeout=15):
    """One blocking call the game makes. Returns a result dict."""
    res = {"ok": False, "wifi": False, "pushed": False, "graph_pct": None,
           "rank": None, "msg": ""}
    wlan = wifi_connect(timeout)
    if not wlan:
        res["msg"] = "no Wi-Fi"
        return res
    res["wifi"] = True
    if token():
        ok, msg = push_player(state)
        res["pushed"] = ok
        res["msg"] = msg
    g = fetch_global()
    if g["graph"]:
        res["graph_pct"] = g["graph"].get("restored_percent")
    if g["leaderboard"]:
        h = handle()
        for s in g["leaderboard"].get("standings", []):
            if s.get("handle") == h:
                res["rank"] = s.get("rank")
                break
    res["ok"] = True
    return res
