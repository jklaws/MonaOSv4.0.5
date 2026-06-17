# MonaOS 4.0.5

The GitHub Hackable Conference Badge ships with MonaOS 4.0.3. Great little
machine. But 2026 is creeping up and there was still no updated OS, so I built
the one I wanted. This isn't official — it's my vision for what the GitHub
Universe 2026 badge could run.
It's built on the **Tufty 2350 badge firmware v2.0.2** (10 Apr 2026) — the
`badgeware` runtime, with v2.0.1's new `badge` module and v2.0.2's PicoVector
fixes. I just leaned on that newer API and filled in everything I kept wishing
the badge did.

## What's new

**Apps — new and updated**
- **Agenda** — live conference schedule pulled from your own GitHub repo in real
  time, cached offline, with now/next + a countdown.
- **Badge** — redesigned ID screen with selectable features and scannable QR codes.
- **Setup** — a phone companion; do the whole setup from your phone instead of
  fighting five buttons.
- **Commit Dash** — new game. Geometry-Dash-inspired, played on your contribution
  graph: real commits shape the level, collectible stars, bug enemies, speed score
  with C→S+ grades.
- **Mona Noir** — new noir hacking game. Crack-the-grid minigame, GitHub pin
  collection, a chase for the rare Rubber Duck, speed score + grades.
- **Bug Bash** — new game. A fast, arcade bug-squashing romp with Mona.
- **Mona Pet** — full visual refresh: new sprites, cleaner room, real-time decay.
- **Gallery** — reworked on the new API, plus a fresh set of images.
- **Flappy, Sketch, Quest** — existing apps, all reworked on the new API.
- **Settings and Wi-Fi setup** rounding it out.

**New Tufty 2350 / badgeware API I'm now using**
- `scale_blit` for scaled sprite drawing
- `SpriteSheet` animations (`frame()` auto-loops)
- `shape.custom` for real vector shapes
- the input model: `pressed` / `held` / `released` / `changed`
- `screen.width` / `screen.height`
- per-app antialiasing (X2 for smooth UI, OFF for fast games)

**Platform & performance**
- Default build runs at the firmware's **200 MHz**; an **optional 250 MHz
  overclock build** (`MonaOS-4.0.5-250mhz-with-filesystem.uf2`, attached) is
  ~20% faster — Commit Dash 21→26, Mona Noir 27→33, Mona Pet 19→23 fps.
- No PSRAM; ample heap headroom, no OOM (lazy-load + LRU eviction + `gc`).
- Reboot-safe Wi-Fi fetch and atomic, crash-safe file writes.
- **Corpsavage** — an MIT-licensed 1-bit pixel font family at 6/7/8/9 px.
- A per-user "badge repo" convention: `github.com/<handle>/badge` backs every
  networked feature.
- Upgraded the **simulator** to match the new API (real `.ppf` font rendering,
  `scale_blit`, the new input model) so every app can be built and screenshotted
  on a laptop instead of reflashing the badge.

## Notes
- Unofficial / community build — a love letter to the badge team, not a
  replacement. If any of it is useful, take it.
- The public source ships without the per-device signing key and with empty
  config; run Setup (or copy `secrets.example.py`) to configure your badge.

Hat-tip to @martinwoodward, @jldeen, and @peckjon for the inspiration — would
genuinely love your take on this.

I waited for the update. Then I built it.
