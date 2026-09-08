#!/usr/bin/env python3
"""Verify that write commands actually reach the speakers.

Three phases, in increasing order of consequence. Every phase is reversible
and none can make your system louder than it already is.

  led     silent. Changes the front LED colour. Proves the write path works.
  volume  writes a much QUIETER level, then restores. Needs audio playing.
  mute    mutes, then unmutes. Needs audio playing.
"""
import argparse, sys, time
sys.path.insert(0, "genlc/src")
import hid
from genlc import const, sam, transport
from genlc.gnet import GNetMessage, GNetException


def ask(q):
    return input(f"  >>> {q} [y/N] ").strip().lower().startswith("y")


def keepalive(sg):
    """Monitors drop offline after a few seconds of bus silence and forget
    their assigned address, so nudge them before every interactive step."""
    try:
        sg.stay_online()
    except GNetException:
        pass


def with_retry(sg, fn):
    """Run fn(); on a lease expiry, re-discover and try once more."""
    try:
        return fn(sg.devices)
    except GNetException:
        mons = [m for m in sg.discover_monitors(all=True) if m.address != 1]
        return fn({m.address: m for m in mons})


def phase_led(sg, mons):
    print("== LED test (silent) ==")
    print("  Watch the front LEDs on all three cabinets.\n")
    results = []

    def paint(colour):
        def go(devs):
            for m in devs.values():
                if m.address != 1:
                    m.bypass(led_color=colour, led_pulsing=False)
        return go

    for colour in ("red", "yellow", "green"):
        keepalive(sg)
        with_retry(sg, paint(colour))
        time.sleep(0.3)
        results.append(ask(f"Did all three LEDs turn {colour.upper()}?"))
    keepalive(sg)
    with_retry(sg, paint("green"))
    print(f"\n  LED writes reaching the monitors: {'YES' if all(results) else 'NO / partial'}")
    return all(results)


def phase_volume(sg, mons, cur_db):
    print("\n== volume test ==")
    print(f"  Current pot position: {cur_db:.1f} dBFS")
    print("  Play some audio at your normal listening level first.")
    keepalive(sg)
    if not ask("Is audio playing now?"):
        print("  skipped"); return None
    print("  Writing -120 dBFS (essentially silence)...")
    sg.set_volume_glm(-120.0)
    time.sleep(0.5)
    went_quiet = ask("Did the sound go (near) silent?")
    print(f"  Restoring {cur_db:.1f} dBFS...")
    sg.set_volume_glm(cur_db)
    time.sleep(0.5)
    came_back = ask("Did the sound come back?")
    print(f"\n  set_volume_glm works: {'YES' if went_quiet and came_back else 'NO'}")
    if went_quiet and not came_back:
        print("  NOTE: nudge the volume knob to resync the hardware pot.")
    return went_quiet and came_back


def phase_mute(sg, mons):
    print("\n== mute test ==")
    print("  NOTE: CID_BYPASS_QUERY is marked 'guesswork' upstream, so this")
    print("        is the least certain command we have.")
    keepalive(sg)
    if not ask("Is audio still playing?"):
        print("  skipped"); return None
    keepalive(sg)
    for m in mons:
        m.mute()
    time.sleep(0.4)
    muted = ask("Did the sound stop?")
    keepalive(sg)
    for m in mons:
        m.mute(mute=False)
    time.sleep(0.4)
    back = ask("Did the sound come back?")
    print(f"\n  mute/unmute works: {'YES' if muted and back else 'NO'}")
    return muted and back


def read_pot_db(dev):
    from genlc.gnet import GNetMessage
    for _ in range(6):
        m = GNetMessage(1, const.CID_POLL)
        raw = transport.USBTransport.escape(bytes(m))
        dev.write(bytes((0, 0x80 + len(raw))) + raw)
        segs = []
        while True:
            pkt = dev.read(64, 300)
            if not pkt:
                break
            segs.append(bytes(pkt))
            if bytes(pkt)[1:].rstrip(b"\0").endswith(bytes((const.GNET_TERM,))):
                break
        if not segs:
            continue
        msg = bytes(transport.USBTransport.unescape(
            bytearray().join(s[1:] for s in segs).rstrip(b"\0")))
        if len(msg) >= 24:
            return int.from_bytes(msg[17:21], "big", signed=True) / 10.0
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phases", nargs="*", default=["led"],
                    choices=["led", "volume", "mute"])
    a = ap.parse_args()

    dev = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
    with dev:
        sg = sam.SAMGroup(transport.USBTransport(dev))
        sam.USBAdapter(sg)
        mons = [m for m in sg.discover_monitors(all=True) if m.address != 1]
        print(f"== monitors: {[m.address for m in mons]} ==\n")
        cur = read_pot_db(dev)
        if cur is None:
            print("Could not read the pot; aborting."); return 1

        if "led" in a.phases:
            phase_led(sg, mons)
        if "volume" in a.phases:
            phase_volume(sg, mons, cur)
        if "mute" in a.phases:
            phase_mute(sg, mons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
