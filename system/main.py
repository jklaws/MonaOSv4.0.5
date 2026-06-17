# MonaOS 4.0.5 launcher boot — invoked by frozen main via __import__("/system/main")
import badgeware  # noqa: F401
from badgeware import launch, set_brightness
import machine
import powman
import os

# Self-heal: the frozen `secrets`/`wifi` import chain hard-crashes ANY app that
# imports it when /secrets.py is missing (e.g. after a filesystem reset). Create
# an empty one at boot so no badge ever crashes on a fresh/wiped device — Setup
# fills in the real values. Atomic (temp + rename) per the FS-durability rules.
try:
    open("/secrets.py").close()
except OSError:
    try:
        with open("/secrets.tmp", "w") as _sf:
            _sf.write('WIFI_SSID = ""\nWIFI_PASSWORD = ""\nGITHUB_USERNAME = ""\nGITHUB_TOKEN = ""\n')
        os.rename("/secrets.tmp", "/secrets.py")
    except Exception:
        pass

# Apply the saved screen brightness (set in the Settings app, stored in
# /settings.json). Runs once at boot; the backlight level then persists across
# app launches. Defaults to a comfortable level if no setting exists yet.
try:
    import json
    with open("/settings.json") as _f:
        _b = json.load(_f).get("brightness", 0.6)
except Exception:
    _b = 0.6
try:
    set_brightness(max(0.15, min(1.0, _b)))
except Exception:
    pass

# Restore the system clock from the battery-backed hardware RTC (PCF85063A) so
# time.localtime() is correct across power cycles. Set the time via Settings >
# Sync time (NTP). Instantiating RTC() copies the persisted hardware time into
# the system clock on a cold boot.
try:
    import badgeware.rtc
    badgeware.rtc.RTC()
except Exception:
    pass

badge.poll()

# Play the boot cinematic only on a cold power-on. App-exit and soft resets come
# through as WAKE_WATCHDOG (machine.reset()), which we skip so the intro doesn't
# replay every time you return to the launcher (matches original MonaOS behaviour).
try:
    _cold_boot = powman.get_wake_reason() != powman.WAKE_WATCHDOG
except Exception:
    _cold_boot = True
if _cold_boot:
    launch("/system/apps/startup")

app = launch("/system/apps/menu")
# Chain app launches: an app's update() may RETURN another app's path to open it
# directly (e.g. the badge's "not set up" screen returns the Setup path on B).
# launch() surfaces that via the app's on_exit, so we keep launching until an
# app exits to the launcher (returns None), then reboot back to the menu.
while app:
    while badge.pressed() or badge.held() or badge.released():
        badge.poll()
    app = launch(app)
machine.reset()
