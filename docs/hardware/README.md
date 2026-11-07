# Hardware documentation

Hardware facts the control software must be built against. One spec per device,
plus one evidence log per unit under test.

| ID | Document | Device | Status |
| --- | --- | --- | --- |
| HW-SPEC-001 | [smartusbhub-pro-4ch.md](./smartusbhub-pro-4ch.md) | SmartUSBHub Pro 4CH USB2.0 | Draft — verified in part |
| HW-VER-001 | [verification.md](./verification.md) | Unit on this host | CMD port not yet observed |

## Evidence rules

Every hardware claim carries one of these tags:

| Tag | Meaning |
| --- | --- |
| `OBS` | Measured on the real unit — names the command and output |
| `DOC` | Stated in the vendor datasheet or user guide |
| `PROTO` | Stated in the vendor communication protocol document |
| `SDK` | Present only in vendor SDK source, not in the public protocol document |
| `INF` | Derived by reasoning from the above |
| `UNK` | Not established; tracked with an ID in the verification log |

When two sources disagree, the higher row wins, and the disagreement is recorded:

1. `OBS` — what the unit actually does.
2. `DOC` / `PROTO` — what the vendor publishes.
3. `SDK` — what the vendor's own implementation assumes.
4. `INF` — our reasoning.

Never promote an `INF` or an `SDK` fact to `DOC` by repeating it.

## Scope of this folder

This folder describes the device, not our software:

- interfaces, connectors, indicators and controls;
- power paths, limits, protection and budget;
- switching behaviour and persistent settings;
- measurement ranges, resolution and wire encoding;
- the physical control interface and the commands the device actually supports;
- what is still unknown, and how to confirm it.

Byte-level frame layout, timing and parser rules belong in
`docs/contracts/protocols.md` once the control code is designed. Do not duplicate
them here.

## Adding another device

1. Copy the section structure of `smartusbhub-pro-4ch.md` to `<device>.md`.
   Keep the same section order and the same evidence tags.
2. Add a row to the table above.
3. Add the unit's observations to `verification.md`, or to a new
   `verification-<device>.md` when more than one unit is tracked.
4. Record every capability difference explicitly. Shared behaviour stays in
   the device spec; do not create a shared file until two devices actually
   need it.
5. Number new constraints from `HW-C-101` upward per device so IDs never
   collide.

## Source copy

`reference/smartusbhub/` is the vendor project, kept read-only for study. It is
not part of our build or our package. See `verification.md` §6 for paths and the
license note.
