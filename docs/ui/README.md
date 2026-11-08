# UI documentation

One page, one interaction model: a keyboard-driven terminal control page drawn
with ANSI control sequences, with a menu that opens over it. The mockup is
the visual truth.

| ID | Document | Purpose | Status |
| --- | --- | --- | --- |
| UI-MENU-002 | [menu.md](./menu.md) | Page spec: frame, menu, Device, states, keys, tokens | Implemented |
| — | [mockup/index.html](./mockup/index.html) | Reference rendering of the sixteen frames | Approved |
| — | [Software architecture](../architecture/overview.html) | Layer and module view | Implemented |

## What shapes the screen

- ANSI SGR and cursor addressing directly. No curses, no third-party widget
  set. Python standard library only.
- POSIX terminal. Linux first; macOS supported, with `--port` required until
  `ioreg` discovery is verified on a Mac.
- 80x24 baseline, 60x16 minimum. UTF-8 box drawing with an ASCII fallback.
- No background colour. The canvas is the terminal's own. Colour appears only
  on state values, so the screen never fights the user's theme.
- The device is real hardware: a keypress can remove VBUS from a running
  device. The screen never implies a value is live when it is not.
