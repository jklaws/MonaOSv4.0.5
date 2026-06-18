# Firmware runtime add-ons

These live in the **badgeware runtime** (the frozen `modules/common` of the
Tufty 2350 firmware build), not in `system/`. Drop them into a v2.0.2
(`bw-1.27.0`) build's `modules/common/` and rebuild to include them.

## QwSTPad I²C gamepad support

- `qwstpad.py` — the Pimoroni QwSTPad driver (TCA9555), default address `0x21`.
- `badge.py` — the `badgeware` Badge class with the gamepad merged into input.

How it works: on boot (and via a ~1 s hot-plug retry) the Badge probes **only
`0x21`** and, if a pad is there, reads it every `badge.poll()` and folds its
buttons into `badge.pressed()/held()/released()`. The mapping uses the symbolic
`BUTTON_*`, so it resolves to **whichever board's** GPIOs are in `pins.csv` —
the same code is correct on the GitHub Hackable Badge and the retail Tufty 2350,
no pin crossing. Button map: `U/D→UP/DOWN`, `A→A`, `B/Y→B`, `X→C`, `L→A`, `R→C`,
`+/-→HOME`. With no pad attached it's a no-op.

Note: `0x21` only — the QwSTPad's alt addresses (`0x23/0x25/0x27`) collide with
common Qw/ST sensors (e.g. the Multi-Sensor Stick's LTR-559 at `0x23`), so we
never probe them.
