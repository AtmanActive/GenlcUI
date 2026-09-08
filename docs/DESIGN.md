# GenlcUI design

## Volume: the knob is master

GenlcUI follows GLM5's model rather than inventing its own, because Genelec's
design encodes a safety property worth keeping:

> **You can only recall a level you have physically set and heard.**

Concretely:

- **No draggable software fader, and no numeric entry for level.** A mouse
  slip or a fat-fingered number is a hearing hazard, and the mouse is the
  least reliable input on the desk.
- **The hardware potentiometer is the master.** The UI shows its position;
  it does not pretend to move it (it cannot -- software writes do not move
  the pot, see docs/PROTOCOL.md).
- **Two level presets**, matching GLM5. Clicking one temporarily overrides
  the knob. Touching the knob takes control straight back, and the preset
  button deselects.
- **Presets are captured from the knob, never typed.** To store a preset you
  turn the physical knob until it sounds right, then commit that reading to a
  slot. The level you store is by construction a level you just listened to.

### Mirroring the knob is our job

An earlier draft of this document asserted that the adapter arbitrates by
itself and GenlcUI needed no takeover logic. **That was wrong**, and it was
inference from GLM5's documentation rather than measurement.

Measured: with GenlcUI running, turning the knob moved the on-screen readout
but did not change the speakers at all. On exit, control returned to the
adapter and the knob worked again immediately.

So while a software controller holds the bus, the adapter **stops applying the
pot** and only reports its position. GLM5's documented behaviour ("as soon as
the knob is touched, the volume goes back to what the knob sets") is GLM5
mirroring the knob in software, not firmware arbitration.

GenlcUI therefore:

1. **mirrors the pot to `CID_VOLUME_GLM` whenever its reading changes** --
   edge-triggered, so a still knob produces no traffic;
2. asserts the pot position on connect, so taking the bus never moves the
   level;
3. writes a preset level when one is clicked, which holds until the pot next
   moves and reclaims control;
4. restores the pot position on exit, so quitting with a preset active does
   not leave the speakers stranded at that level.

The mirror *is* the arbitration. Last writer wins, and the user's hand is
always the most recent writer.

### The ceiling does not apply to the knob

Mirroring is deliberately unclamped. The ceiling exists to guard writes with
no physical act behind them; the pot's position is one the user just chose and
heard. Clamping it would make the hardware feel broken above the limit, and
would be a regression from how the system behaves with no software running.

## Volume safety ceiling

A configurable ceiling (default **-30 dBFS**, the loudest the author
tolerates) clamps every *programmatic* write: wake, unmute, D-Bus and CLI
calls. These have no physical act behind them, so they need a guard.

Preset capture is a different case: the level came from the knob, so the user
has already heard it. If a captured preset would exceed the ceiling, the UI
asks whether to raise the ceiling rather than silently clamping -- silently
storing something other than what was just heard would break the very property
the design exists to protect.

## Wake

`wake()` takes its level from the **current pot position**, clamped to the
ceiling. Genelec documents that SAM monitors default to starting at maximum
level in standalone mode, so waking without setting a level first hands
control to whatever is in speaker flash. Taking the knob's position is both
safe and unsurprising: the system comes back where the physical control says
it should be.

## Mute

`set_volume(-130)`, the documented bottom of the fader, restoring the previous
level on unmute. There is no verified mute command -- see docs/PROTOCOL.md for
why the obvious candidate is not one.

## Identity

Everything user-visible keys off **serial number**. Addresses are leases that
expire after ~2-3s of bus silence and get reassigned on every re-discovery, so
UI ordering, names and per-speaker settings must never depend on them.

## Process

The app stays resident (tray icon) because it must: the keepalive heartbeat
that holds the address leases has to run continuously, and the HID device is
exclusive-open. A connect-on-demand design would find its addresses expired
every time.
