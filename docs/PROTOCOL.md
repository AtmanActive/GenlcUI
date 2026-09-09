# GLM / GNet protocol notes

Findings from live reverse engineering against a real rig, extending what
`genlc/` (vendored from [markbergsma/genlc](https://github.com/markbergsma/genlc))
implements. Everything here was observed on:

- GLM Adapter, fw `1.3.2.5053`, with calibration mic attached
- Genelec 7350A subwoofer
- 2x Genelec 8330A
- All three previously grouped and calibrated with [GLM5](https://www.genelec.com/glm) on Windows

## Message framing

Confirmed as upstream documents it. CRC-16/GSM over address+command+data,
verified against every captured message (`libscrc.gsm16(msg[:-3])`).

A **bare ACK** is `01 09 5d e7 7e` -- valid CRC, zero payload.

### Byte 0 is NOT the source address

Upstream never reads `msg[0]`, and it is tempting to assume it identifies the
responder. It does not: it is `0x01` in every response regardless of which
address was queried. There is no source attribution in the response, so
request/response correlation depends entirely on ordering discipline.

## Responses are synchronous

One response per request, arriving in ~2.8 ms. There is no late/asynchronous
delivery. (An earlier hypothesis that responses were asynchronous was wrong.)

## Monitor poll responses are tag-value encoded

`sam.SAMMonitor.poll()` reads fixed offsets (`resp[1]`, `resp[6:7]`,
`resp[12:13]`). That is incorrect and produces impossible values such as
`input_dBFS=66` and `output_dBFS=69` -- those are tag bytes being read as
measurements.

The actual encoding is a flat sequence of tag-value pairs:

    tag & 0x80  ->  value is 2 bytes, big-endian
    tag & 0x80 == 0 -> value is 1 byte

This parses to the byte across different message lengths and models
(23/23 and 24/24 bytes consumed for the 7350A and 8330A respectively).

The field set **varies by model** -- the 7350A emits tag `0x46` and omits
`0x81`; the 8330As do the reverse. Any fixed-offset parser is therefore
structurally wrong, not merely mis-indexed.

### Known tags

| Tag            | Meaning                    | Confidence |
|----------------|----------------------------|------------|
| `0x41`/`0x81`/`0x83` | Temperature (degrees C) | Confirmed -- matches independently reported values |
| `0x42`         | ? (-55/-53/-52 signed; plausibly output level) | Unknown |
| `0x43`         | ? (-128 sub, -110 mains)   | Unknown |
| `0x45`         | ? (-110 sub, -119/-118 mains) | Unknown |
| `0x46`         | ? sub-only, `0x80`         | Unknown |
| `0x47`         | ? always `0x01`            | Unknown |
| `0x49`         | ? (96 sub, 95 mains)       | Unknown |
| `0x84`         | ? (353 sub, 703 mains)     | Unknown |
| `0x8a`         | ? always `0x0019` (25)     | Unknown |

## Poll cadence: empty ACK means "no new data"

Monitors refresh their measurements roughly **once per second** and return a
bare ACK when nothing has changed since the last poll. This is a rate limit,
not an error, and not packet loss.

Measured hit rate vs. per-monitor poll interval:

| Poll interval | Data returned |
|---------------|---------------|
| ~0.3 s        | ~31%          |
| ~0.75 s       | ~70%          |
| ~1.5 s        | 100%          |

**Consequence:** poll the adapter fast (10-20 Hz, for knob and mic) and the
monitors slowly (~1 Hz). Treat an empty ACK as "retain previous value".

## Adapter poll response (address 1)

24 bytes total; 19-byte payload. Does *not* use the tag-value encoding above
-- it appears to be a fixed layout.

| Payload offset | Meaning |
|----------------|---------|
| 3..5           | Microphone level, sint24 (upstream already parses this) |
| 9..11          | Unknown, SPL-related |
| 17..18         | **Volume pot position**, signed, tenths of a dBFS |

### Volume

The volume field reads the **physical potentiometer position only**. Writing
`CID_VOLUME_GLM` does not change it (verified: three writes at -120/-110/-100
dBFS left the field pinned at -511).

Scale confirmed two ways: the observed floor is exactly `-1300` = -130.0 dBFS,
and the GLM 4 manual documents the fader range as 0 dBFS down to -130 dBFS.

**Consequence:** a GUI needs a last-writer-wins volume model -- track the
written value, watch the pot register, and adopt the pot position as truth
whenever it changes.

## The adapter yields volume control to software

While a software controller holds the bus (assigning addresses and sending
STAY_ONLINE), the adapter **stops applying the potentiometer to the monitors**.
It continues to report the pot position accurately, but nothing acts on it.
Releasing the bus hands control straight back.

Observed directly: with GenlcUI running, the on-screen readout tracked the
knob perfectly while the speakers ignored it; on Ctrl-C the knob immediately
worked again.

**Consequence:** any application holding this bus MUST mirror the pot position
to `CID_VOLUME_GLM` itself, or it silently breaks the user's volume control
for as long as it runs. This is almost certainly what GLM5 does.

## Knob events are polled, not pushed

Zero unsolicited packets arrive during a 10 s idle listen while turning the
knob. There is nothing to subscribe to.

## CID_BYPASS_QUERY (0x2B) -- do not trust genlc here

genlc models this byte as `{bit 0: mute, bits 1-2: LED colour, bit 3: pulsing}`
and exposes it as `bypass(led_color=...)`. That is wrong, and wrong in a way
that damages a working system.

Sending `led_color="red"` sends value `0x02`. Observed on real hardware:

- the LED goes **steady red**
- audio **keeps playing at its current level** -- it is not a mute
- the monitor **stops responding to volume control**, including the
  hardware potentiometer
- value `0x00` restores normal operation completely

The LED is a *readout of state*, not something the host paints. GLM 5 manual,
Table 5:

| LED | Meaning |
|-----|---------|
| Steady green | Normal state |
| Slowly blinking green | Normal ISS power saving state |
| From yellow to green | Normal operation during device startup |
| Steady yellow | Monitor or subwoofer is not part of the group |
| Steady red | Muted from GLM |
| Flashing red | Signal clip / AES bit errors / near 0 dBFS |
| Flashing yellow | Protection |

Note the manual says steady red means "Muted from GLM", yet audio was never
silenced. The best explanation is that a real GLM mute sets **both** bits --
`0x01` silences, `0x02` locks the volume stage, `0x03` together is what the
manual calls muted. Sending `0x02` alone produces half a mute: the lock
without the silence. **Untested**, and there is no need to test it.

**Consequences for this project:**

1. There is no verified mute command. Mute in the UI is `set_volume(-130)`,
   the documented bottom of the fader: understood, reversible, and
   indistinguishable to the listener.
2. There is no LED colour API. Do not offer one.
3. Only `0x00` is sent. `commands.py` names nothing else.

### Evidence hierarchy

Observed behaviour on real hardware > Genelec's documentation > genlc's
naming. Each of the three disagreed with the next in this one command, in
that order of reliability.

## Sleep is advisory, not authoritative

`CID_WAKEUP` with the shutdown payloads does put monitors into standby, but
they wake themselves again through ISS (Intelligent Signal Sensing). Genelec
documents three things that prevent or end ISS sleep:

* a signal on the analogue input,
* **a bit clock on the digital input** -- audio need not be playing,
* **commands received on the GLM network**.

The third one is ours to control, and getting it wrong is why an early
version's speakers woke a few seconds after every shutdown: the app kept
broadcasting `STAY_ONLINE` (which does exactly what its name says) four times
a second, plus a `RACE` roll-call every two seconds. Sleep must therefore
suppress the heartbeat, discovery, monitor polling and knob mirroring -- see
`Session.asleep`.

The first two are not ours to control. On a digital connection with an open
sink, the bit clock alone keeps the monitors awake indefinitely, so a
commanded sleep will not hold until the source releases the device.

There is also no way to observe the wake: any query that would reveal it is a
GLM network command, which is itself a reason for the monitor to stay awake.
The UI therefore reports sleep as commanded, with a note that the speakers may
wake on their own.

`CID_ISS` appears in genlc's constant list but is unassigned, so the ISS
timeout cannot currently be configured from here. There is a hardware
`ISS Disable` switch on each cabinet's back plate.

## Safety

Genelec documents that at factory default, **SAM monitors start up at maximum
level** in standalone mode. A startup level can be stored into the speakers
(GLM overrides it while connected).

`sam.SAMGroup.wakeup_all()` broadcasts wakeup without setting any volume, so
waking monitors hands control to whatever is stored in their flash.

Rules adopted for this project:

1. **Wake is always volume-first.** Write the intended volume, then wake, then
   re-assert volume once monitors respond. Never wake bare.
2. **Clamp every write** to a user-configurable maximum.
3. **Never send unverified commands.** genlc's identifiers are hypotheses,
   several marked `# FIXME: guesswork` and several more wrong without a
   marker. Check the manual, say plainly when semantics are unknown, and get
   agreement before sending.
4. **Never write store/calibration commands** -- `CID_STORE_USER_PARS`,
   `CID_STORE_CALIBRATION`, `CID_START_VOLUME` stay unimplemented. These are
   what would overwrite a GLM5 calibration held in speaker flash. Volume,
   mute, LED and wake/sleep are all runtime-only and leave flash untouched.

## GLM's own UI behaviour, for reference

The GLM 5 manual notes: "If the GLM Adapter volume controller is connected,
the volume is only set by the controller and the GUI volume control is
disabled." Genelec resolves the two-masters problem by surrendering -- with a
pot attached, their software fader is inert.

GenlcUI does not copy that. Writes are verified to work with the pot
connected, so the UI stays live and the model is last-writer-wins: whoever
moved most recently owns the level. The pot reports position but cannot be
moved by software, so a *change* in its reading is unambiguously the user's
hand and takes over.

## Environment notes

- The adapter enumerates as USB HID `1781:0e39`, exposed as a `hidraw` node
  owned `root:root 0600` by default. See `packaging/udev/`.
- `libscrc` has no wheel for CPython 3.13 and needs Python headers to build;
  CPython 3.12 has a wheel. Worth replacing with a ~6-line pure-Python
  CRC-16/GSM to drop the build dependency entirely.
