# Local badge simulator (headless screenshots)

`badge_simulator.py` is the Pygame `badgeware` engine from badger/home.
`sim_run.py` adapts it to our **2026 firmware API** (bare-name builtins:
screen/color/shape/image/pixel_font/badge/vec2/rect/mat3/OFF/X2/X4/BUTTON_*/State,
`/system/...` path-imports, machine, mock secrets/network) and runs an app
**headlessly** to a PNG — no window or keypress, so it works over SSH/CI and
doesn't depend on the flaky USB device.

## Setup (Python 3.12 — pygame.font is missing on 3.14)
    /opt/homebrew/bin/python3.12 -m venv /tmp/sv
    /tmp/sv/bin/pip install pygame pillow

## Run
    SDL_VIDEODRIVER=dummy /tmp/sv/bin/python simulator/sim_run.py <app> \
        [--frames N] [--out PNG] [--keys "5:A,30:UP+A"] [--set "state=GS.SELECT"] [--dt MS]

- `<app>` = an app name under `system/apps/` (e.g. `commitdash`) or a path to `__init__.py`.
- `--keys` injects button presses on given frames (A/B/C/UP/DOWN/HOME).
- `--set` forces module globals after load, e.g. `--set "state=GS.SELECT;cam=1000.0"`.
- `--root` overrides the firmware `system/` dir (defaults to this repo's firmware).

## Known limits
- `.ppf` fonts aren't parsed → generic font (text looks different from device; layout is right).
- Antialias / blit-scaling are approximations. Good for layout/visual/logic validation,
  not pixel-exact font rendering.
