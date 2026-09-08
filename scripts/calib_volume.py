#!/usr/bin/env python3
"""Confirm the volume scale WITHOUT touching the knob or making noise.

Writes only very quiet volumes (default: never above -100 dB, hard cap -90),
reads the adapter's volume field back, and restores the original value.

If readback == round(written_dB * 10), then the read scale and the write scale
are the same unit, and the GUI can treat knob position and slider position as
one quantity. That is the fact we actually need -- the top of the range is
then implied and never has to be reached.
"""
import argparse, sys, time
sys.path.insert(0, "genlc/src")
import hid
from genlc import const, sam, transport
from genlc.gnet import GNetMessage

PKT, HARD_CAP_DB = 64, -90.0


def read_msg(dev, timeout=300):
    segs = []
    while True:
        pkt = dev.read(PKT, timeout)
        if not pkt:
            return None
        segs.append(bytes(pkt))
        if bytes(pkt)[1:].rstrip(b"\0").endswith(bytes((const.GNET_TERM,))):
            break
        if len(segs) >= 3:
            break
    m = bytearray().join(s[1:] for s in segs).rstrip(b"\0")
    return bytes(transport.USBTransport.unescape(m))


def read_volume_raw(dev, tries=6):
    """Poll the adapter and decode the candidate volume field (bytes 17..20)."""
    for _ in range(tries):
        m = GNetMessage(1, const.CID_POLL)
        raw = transport.USBTransport.escape(bytes(m))
        dev.write(bytes((0, 0x80 + len(raw))) + raw)
        msg = read_msg(dev)
        if msg and len(msg) >= 24:
            return int.from_bytes(msg[17:21], "big", signed=True)
        time.sleep(0.05)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="-120,-110,-100",
                    help="dB values to write (all must be <= -90)")
    args = ap.parse_args()

    levels = [float(x) for x in args.levels.split(",")]
    bad = [x for x in levels if x > HARD_CAP_DB]
    if bad:
        print(f"REFUSING: {bad} exceed the {HARD_CAP_DB} dB safety cap.")
        return 1

    dev = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
    with dev:
        sg = sam.SAMGroup(transport.USBTransport(dev))
        sam.USBAdapter(sg)
        list(sg.discover_monitors(all=True))

        orig = read_volume_raw(dev)
        if orig is None:
            print("Could not read the volume field; aborting without writing.")
            return 1
        print(f"current volume field : {orig}  (= {orig/10:.1f} dB if tenths)")
        print(f"will restore this value when done\n")
        print(f"{'written dB':>11} {'expect':>8} {'readback':>9} {'match':>7}")
        print("-" * 40)

        # Never write a level louder than what is already set.
        levels = [db for db in levels if db <= orig / 10.0]
        if not levels:
            print(f"All test levels are louder than the current {orig/10:.1f} dBFS.\n"
                  f"Nothing to do -- turn the knob up a little and re-run.")
            return 1
        print(f"testing (all quieter than current): {levels}\n")

        results = []
        try:
            for db in levels:
                sg.set_volume_glm(db)
                time.sleep(0.25)
                got = read_volume_raw(dev)
                exp = round(db * 10)
                ok = got == exp
                results.append(ok)
                print(f"{db:>11.1f} {exp:>8d} {str(got):>9} {'YES' if ok else 'no':>7}")
        finally:
            sg.set_volume_glm(orig / 10.0)
            time.sleep(0.25)
            back = read_volume_raw(dev)
            print(f"\nrestored to {orig} -> reads {back} "
                  f"({'ok' if back == orig else 'MISMATCH, move the knob to resync'})")

        print()
        if all(results):
            print("CONFIRMED: read and write use the same scale, tenths of a dB.")
        elif not any(r for r in results):
            got_any = [r for r in results]
            print("Field did NOT track written volume -> it reflects the physical pot\n"
                  "only, and the GUI must track written volume separately.")
        else:
            print("Partial match -- see rows above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
