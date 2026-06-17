# Unified per-user "badge" repo convention.
#
# Every badge capability is backed by a SINGLE repo the user owns:
#     github.com/<handle>/badge
# with each capability namespaced in its own folder, e.g.
#     badge/agenda/agenda.json     <- the agenda app
#     badge/profile/...            <- (future) identity / links
#     badge/mona-noir/...          <- (future) game state
# so a user has one repo for their badge and we add folders as we add features.
#
# READS are public (no token) and come from raw.githubusercontent.com.
# WRITES (creating the repo, pushing files) need a GITHUB_TOKEN with repo scope
# and are handled elsewhere (setup flow); this module is read + cache only.
#
# REBOOT-SAFE CONTRACT: the badge HARD-REBOOTS if the LCD parallel-DMA is mid
# transfer while the cyw43 radio associates. So callers MUST run fetch_json()
# synchronously from inside ONE update() frame, AFTER drawing a "syncing" screen
# and calling display.update() exactly once. The whole Wi-Fi connect + TLS + HTTP
# then runs blocking inside that single frame, so the framework's per-frame
# display.update() never fires during association. See mona_noir/sync.py.
import network
import json
import time
from urllib.urequest import urlopen

REPO = "badge"
UA = "GHBadge"

# "Use this template" one-tap repo creation (Option A): the user scans a QR to
# this URL on their phone, taps Create, names the new repo `badge`. No token.
TEMPLATE_OWNER = ""   # owner of a `badge-template` repo; blank -> create a blank repo
TEMPLATE_REPO = "badge-template"


def template_generate_url():
    # ?name=badge pre-fills the new repo's name on GitHub's "create from template"
    # page, so the user just confirms (owner defaults to the logged-in account).
    if TEMPLATE_OWNER:
        return "https://github.com/%s/%s/generate?name=%s" % (
            TEMPLATE_OWNER, TEMPLATE_REPO, REPO)
    return "https://github.com/new?name=%s" % REPO


def _secret(name, default=""):
    try:
        import secrets
        return getattr(secrets, name, default) or default
    except Exception:
        return default


def handle():
    return _secret("GITHUB_USERNAME", "")


def raw_url(area_path, who=None, bust=False):
    """raw.githubusercontent URL for a file in the badge repo. Fully GitHub-hosted
    (Fastly-CDN backed). The badge reads its OWN repo, manually (button B), and
    caches the result on-device -- so the per-user, spread-out load stays well
    within raw's limits with no external hosting. The ?t= cache-buster fetches a
    fresh copy when the user explicitly syncs."""
    u = "https://raw.githubusercontent.com/%s/%s/main/%s" % (
        who or handle(), REPO, area_path)
    return (u + ("?t=%d" % time.ticks_ms())) if bust else u


def repo_web(who=None):
    return "github.com/%s/%s" % (who or handle(), REPO)


def has_wifi():
    return bool(_secret("WIFI_SSID"))


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
    # accumulate chunks in a list + join once (avoids O(n^2) realloc on the
    # small heap that `data += bytes(...)` per 512B chunk would cause)
    parts = []
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


def _get(url):
    """One HTTP GET. Returns (status, body_bytes_or_None):
    ok | not_found (404) | rate_limited (429) | error."""
    try:
        resp = urlopen(url, headers={"User-Agent": UA})
    except Exception as e:
        msg = str(e)
        if "404" in msg:
            return ("not_found", None)
        if "429" in msg or "rate limit" in msg.lower():
            return ("rate_limited", None)
        return ("error", msg)
    try:
        body = _read(resp)
    finally:
        try:
            resp.close()
        except Exception:
            pass
    return ("ok", body) if body else ("not_found", None)


def fetch_json(area_path, who=None, timeout=15):
    """Fetch + parse a JSON file from the badge repo, reboot-safely.

    Fully GitHub-hosted: reads the user's public repo from raw.githubusercontent
    (no external CDN, no server). Manual sync + on-device cache keep the load low.

    Returns (status, value):
      ("ok", data)          parsed JSON
      ("no_wifi", None)     no Wi-Fi configured / could not associate
      ("not_found", None)   repo or file does not exist yet (404)
      ("rate_limited", None) GitHub throttled us -> keep the cached copy, retry later
      ("error", "msg")      network / parse failure
    Call this inside ONE update() frame, after one display.update().
    """
    if not has_wifi():
        return ("no_wifi", None)
    if not wifi_connect(timeout):
        return ("no_wifi", None)
    status, body = _get(raw_url(area_path, who, bust=True))
    if status != "ok":
        return (status, None)
    try:
        return ("ok", json.loads(body))
    except Exception as e:
        return ("error", "bad json: %s" % e)
