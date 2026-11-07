# UI documentation

One screen, one interaction model: a keyboard-driven terminal dashboard drawn
with ANSI control sequences.

| ID | Document | Purpose | Status |
| --- | --- | --- | --- |
| UI-DASH-001 | [dashboard.md](./dashboard.md) | Screen spec: frame, states, keys, tokens | Implemented |
| — | [mockup/index.html](./mockup/index.html) | Static reference rendering of the four states | Reference |
| — | [mockup/preview.py](./mockup/preview.py) | Runnable ANSI preview of the four states | Reference |
| — | [Software architecture](../architecture/overview.html) | Layer and module view | Implemented |

Run the preview in a real terminal:

```
python3 docs/ui/mockup/preview.py
```

`1-4` switches state, `j/k` moves the selection, `space` and `d` toggle in the
LIVE demo, `q` quits. `--dump <state> --no-color` prints one frame without a
terminal.

## What shapes the screen

- ANSI SGR and cursor addressing directly. No curses, no third-party widget
  set. Python standard library only.
- POSIX terminal. Linux first; macOS supported, with `--port` required until
  `ioreg` discovery is verified on a Mac.
- 80x24 baseline, 60x16 minimum. UTF-8 box drawing with an ASCII fallback.
- Colour is decoration. Every state is readable in monochrome.
- The device is real hardware: a keypress can remove VBUS from a running
  device. The screen never implies a value is live when it is not.
