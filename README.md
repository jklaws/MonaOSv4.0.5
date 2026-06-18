# MonaOS 4.0.5

An unofficial, community build of the OS for the **GitHub Hackable Conference
Badge** — a vision of what it could run for **GitHub Universe 2026**.

The badge ships with **MonaOS 4.0.3** (built on the Pimoroni **Tufty 2350**).
MonaOS 4.0.5 is the app/OS layer on top of the **Tufty 2350 badge firmware
v2.0.2** (10 Apr 2026) — the `badgeware` runtime that in v2.0.1 replaced the old
`io` module with the expanded **`badge`** module, and in v2.0.2 shipped the
PicoVector fixes (vector clipping, image-blit overflow, FAT corruption). Same
hardware, newer API, and a stack of new apps and capabilities. It is **not** an
official GitHub release — a love letter to the badge, built while waiting for an
update.

> **Heads up:** this is a fan/community project. It builds on the official badge
> firmware and the `badgeware` runtime. Flash at your own risk.

## What's in 4.0.5

### Apps
- **Agenda** — pulls a conference schedule **live from your own GitHub repo**
  (`github.com/<handle>/badge/agenda/agenda.json`), caches it on-device, shows
  a live now/next banner + countdown, and re-syncs on demand (hold A+C).
- **Badge** — redesigned identity screen with selectable features and scannable
  **QR codes** (your profile / your badge repo).
- **Setup** — a **phone companion**: the badge raises an access point and serves
  a mobile-first setup page so you configure Wi-Fi + your GitHub handle from your
  phone instead of typing on 5 buttons.
- **Commit Dash** — a Geometry-Dash-inspired auto-runner where the level *is*
  your GitHub contribution graph. Collectible stars, bug enemies, a speed-based
  score and C→S+ grades.
- **Mona Noir** — a noir hacking game: crack nodes on a circuit grid before your
  signal runs out, collect GitHub pins, chase the rare Rubber Duck. Speed score
  + C→S+ grades, per-node best.
- **Bug Bash** — a fast arcade bug-squashing game.
- **Mona Pet** — Refreshed with Higher Res Visuals and real-time RTC decay that drives the exeperience(day/night room).
- Plus **Flappy, Gallery, Sketch, Quest**, daily bonuses, and more — the
  existing apps reworked on the new API for consistency.

### Platform
- Rebuilt rendering + input on the newer badgeware API: `scale_blit`,
  `SpriteSheet` animations (`frame()` auto-loops), `shape.custom` vector shapes,
  the `pressed` / `held` / `released` / `changed` input model, `screen.width/height`.
- Per-app antialiasing: smooth (X2) for UI, **OFF** for fast games.
- Lazy-loaded + LRU-evicted sprites with `gc` passes, so games run with no PSRAM.
- **`corpsavage`** — an MIT-licensed 1-bit pixel font family at 6/7/8/9 px.
- A per-user **"badge repo" convention**: `github.com/<handle>/badge` backs every
  networked feature, namespaced by folder (`badge/agenda/…`, etc.).

### Measured performance (on hardware)
The default build runs at the firmware's **200 MHz**. An **optional 250 MHz
overclock build** (see Releases) is ~20% faster everywhere:

| Game | 200 MHz (default) | 250 MHz (optional OC) |
|---|---|---|
| Commit Dash | ~21 fps | ~26 fps |
| Mona Noir | ~27 fps | ~33 fps |
| Mona Pet | ~19 fps | ~23 fps |

No OOM on the no-PSRAM heap (tens to ~200 KB free depending on the app).

## Repository structure

```
system/            # the badge filesystem (flashed to the device)
  apps/            #   one folder per app (__init__.py + assets)
  assets/          #   shared fonts + sprites
  *.py             #   core modules (ghbadge, fsutil, main, …)
simulator/         # headless/desktop simulator (test apps without a badge)
secrets.example.py # template for the per-device Wi-Fi/GitHub config
```

## Getting started

### Flash it — that's all you need
Grab the `.uf2` for **your board** from this repo's **Releases**. The GitHub
Hackable badge and the retail Tufty have different button/electrical pins and are
**not** cross-compatible, so pick the matching image:

**GitHub Hackable Conference Badge**
- **`MonaOS-4.0.5-with-filesystem.uf2`** — standard build (200 MHz).
- **`MonaOS-4.0.5-250mhz-with-filesystem.uf2`** — optional overclock, ~20% faster.

**Retail Pimoroni Tufty 2350**
- **`MonaOS-4.0.5-tufty2350-with-filesystem.uf2`** — corrected Tufty pin map + 8 MB PSRAM enabled, 250 MHz.

Then:
1. Connect the badge over USB-C.
2. Hold **BOOT** (far left, on the back) and briefly tap **RESET**.
3. An `RP2350` drive appears — drag the `.uf2` onto it.
4. The badge reboots into MonaOS 4.0.5. On first boot, open the **Setup** app,
   scan the QR with your phone, and enter your Wi-Fi + GitHub handle. Done — no
   other steps. (The `-with-filesystem` image already includes every app.)

### Updating apps later (developers only — not needed to run MonaOS)
Iterating on an app without reflashing? Copy `system/` over with `mpremote`:

```
mpremote connect <port> fs cp -r system :/system
```

### Per-user data (optional)
Create a public repo named **`badge`** under your account. Apps read from it,
e.g. `badge/agenda/agenda.json` for the Agenda. Reads are public (no token);
only write features need a `GITHUB_TOKEN`.

## Testing apps with the simulator

The simulator renders any app to a PNG on your computer — no badge required.
It renders the real `.ppf` pixel fonts and supports `blit`/`scale_blit` and the
full input model, so what you see matches the hardware.

```
python3 -m venv .venv && .venv/bin/pip install pygame pillow
SDL_VIDEODRIVER=dummy .venv/bin/python simulator/sim_run.py commitdash \
    --frames 16 --out /tmp/out.png
```

`--keys "5:A,30:UP+A"` injects button presses per frame; `--set "k=v;…"` forces
module globals (e.g. a game state); `--gui` opens an interactive window.

## Creating your own apps

Each app is a folder under `system/apps/<name>/` with an `__init__.py` that
imports `badgeware` (which injects builtins: `screen`, `color`, `shape`,
`image`, `vec2`, `rect`, `mat3`, `pixel_font`, `rom_font`, `badge`, `run`,
`display`, `SpriteSheet`, `State`, `BUTTON_*`, `OFF/X2/X4`) and ends with
`run(update)`. `update()` returns `None` to keep looping, or a path to chain to
another app. The menu auto-discovers any folder with an `__init__.py`
(alphabetical; an optional `name.txt` overrides the display label, and
`icon.png` is a 24×24 icon).

## License

MIT — see [LICENSE](LICENSE). The `corpsavage` font is MIT (derived from
petme128). The bundled `somepx` fonts are licensed assets — don't redistribute
modified versions.
