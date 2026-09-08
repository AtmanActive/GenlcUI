#!/usr/bin/env python3
"""Protocol diagnostics for the GLM adapter.

All phases are read-only; nothing is written to the speakers.

  drain   - does the adapter push unsolicited packets (e.g. knob events)?
  poll    - raw poll responses, to test the "byte 0 == source address" theory
  knob    - differential capture: baseline vs. knob-turning, per-byte analysis
  mic     - live mic SPL, to compare our number against what GLM5 shows
"""
import argparse
import json
import statistics
import sys
import time

sys.path.insert(0, "genlc/src")

import hid  # noqa: E402
from genlc import const, sam, transport, util  # noqa: E402
from genlc.gnet import GNetMessage  # noqa: E402

PKT = 64
OUT = "/tmp/claude-1000/-home-atmanactive-Documents-Github-GenlcUI/4aba7e52-4320-40e8-928f-f1f5cb640c8e/scratchpad"

# Offsets into the reassembled message: [src][ack] + payload + [crc][crc][term]
PAYLOAD_OFF = 2
# Payload bytes documented in sam.py USBAdapter.poll as microphone-related
MIC_PAYLOAD_BYTES = set(range(3, 6)) | set(range(9, 12))


def hexs(b) -> str:
    return " ".join(f"{x:02x}" for x in b)


def drain(dev, timeout=60, label="drain", quiet=False):
    got = []
    while True:
        pkt = dev.read(PKT, timeout)
        if not pkt:
            break
        got.append(bytes(pkt))
    if got and not quiet:
        print(f"  [{label}] {len(got)} stray packet(s):")
        for p in got:
            print(f"    {hexs(p[:24])} ...")
    return got


def read_msg(dev, timeout=300):
    """Read one reassembled message, without transport.py's assertions."""
    segs = []
    while True:
        pkt = dev.read(PKT, timeout)
        if not pkt:
            return None, segs
        segs.append(bytes(pkt))
        if bytes(pkt)[1:].rstrip(b"\0").endswith(bytes((const.GNET_TERM,))):
            break
        if len(segs) >= 3:
            break
    msg = bytearray().join(s[1:] for s in segs).rstrip(b"\0")
    return bytes(transport.USBTransport.unescape(msg)), segs


def send_poll(dev, addr):
    m = GNetMessage(addr, const.CID_POLL)
    raw = transport.USBTransport.escape(bytes(m))
    dev.write(bytes((0, 0x80 + len(raw))) + raw)


def poll_once(dev, addr):
    drain(dev, 5, quiet=True)
    send_poll(dev, addr)
    msg, _ = read_msg(dev)
    return msg


# --------------------------------------------------------------------------


def phase_drain(dev, seconds):
    print(f"== idle listen, {seconds}s -- TURN THE VOLUME KNOB during this ==")
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < seconds:
        pkt = dev.read(PKT, 200)
        if pkt:
            n += 1
            print(f"  +{time.monotonic()-t0:5.2f}s  {hexs(bytes(pkt)[:24])} ...")
    print(f"  unsolicited packets: {n}"
          + ("  -> knob is PUSH-based, we can subscribe" if n else
             "  -> nothing pushed; knob must be polled"))


def phase_poll(dev, addrs, rounds):
    print("== raw poll responses ==")
    print("   asked = address we sent to;  b0 = first response byte")
    mism = 0
    for r in range(rounds):
        for a in addrs:
            drain(dev, 5, f"pre-poll a={a}")
            send_poll(dev, a)
            msg, segs = read_msg(dev)
            if msg is None:
                print(f"  r{r} asked={a:3d}  <no response>")
                continue
            ok = msg[0] == a
            mism += not ok
            print(f"  r{r} asked={a:3d}  b0={msg[0]:3d}  ack=0x{msg[1]:02x}  "
                  f"len={len(msg):2d}  segs={len(segs)}  {hexs(msg)}"
                  f"{'' if ok else '   <<< MISMATCH'}")
        print()
    print(f"  mismatches: {mism}")
    if mism == 0:
        print("  -> byte 0 IS the source address. We can validate every response.")


def capture(dev, addr, seconds, label):
    samples, t0 = [], time.monotonic()
    while time.monotonic() - t0 < seconds:
        msg = poll_once(dev, addr)
        if msg:
            samples.append(list(msg))
        time.sleep(0.05)
    print(f"  captured {len(samples)} samples ({label})")
    return samples


def analyse(idle, moved):
    """Per-byte-column comparison of two capture segments."""
    if not idle or not moved:
        print("  not enough samples")
        return
    n = min(len(idle[0]), len(moved[0]))
    print(f"\n  {'msg':>3} {'payl':>4} | {'idle range':>14} {'idle uniq':>9} "
          f"| {'knob range':>14} {'knob uniq':>9} | verdict")
    print("  " + "-" * 84)
    for i in range(n):
        ic = [s[i] for s in idle if i < len(s)]
        mc = [s[i] for s in moved if i < len(s)]
        iu, mu = len(set(ic)), len(set(mc))
        p = i - PAYLOAD_OFF
        plabel = str(p) if p >= 0 else "-"
        static_idle = iu == 1
        moves = mu > 1
        if static_idle and moves:
            verdict = "*** KNOB CANDIDATE ***"
        elif p in MIC_PAYLOAD_BYTES:
            verdict = "mic (known)"
        elif iu == 1 and mu == 1 and ic[0] == mc[0]:
            verdict = "constant"
        elif iu > 1 and mu > 1:
            verdict = "noisy both"
        else:
            verdict = ""
        print(f"  {i:>3} {plabel:>4} | {min(ic):3d}-{max(ic):3d}"
              f"{'':>7} {iu:>9} | {min(mc):3d}-{max(mc):3d}{'':>7} {mu:>9} "
              f"| {verdict}")


def phase_knob(dev, seconds):
    print("== differential knob capture ==")
    input(f"  1) Do NOT touch the knob. Press Enter to record {seconds:.0f}s baseline... ")
    idle = capture(dev, 1, seconds, "baseline")
    input(f"  2) Now turn the knob slowly min->max for {seconds:.0f}s. Press Enter to start... ")
    moved = capture(dev, 1, seconds, "knob moving")
    analyse(idle, moved)
    path = f"{OUT}/knob_capture.json"
    with open(path, "w") as f:
        json.dump({"idle": idle, "moved": moved}, f)
    print(f"\n  raw samples saved to {path}")


def phase_mic(dev, seconds):
    print(f"== live mic SPL for {seconds}s ==")
    print("   Compare these against the dB number GLM5 shows for the same room.")
    vals = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        msg = poll_once(dev, 1)
        if not msg or msg[0] != 1:
            continue
        resp = msg[PAYLOAD_OFF:-3]
        if len(resp) < 6:
            continue
        raw = int.from_bytes(resp[3:6], byteorder="big", signed=True)
        db = util.dBSPL_from_sint24(raw) if raw > 0 else 0.0
        vals.append(db)
        print(f"  raw={raw:9d}  genlc={db:7.2f} dBSPL   {hexs(resp[:8])}")
        time.sleep(0.25)
    if vals:
        print(f"\n  min {min(vals):.2f}  max {max(vals):.2f}  "
              f"mean {statistics.mean(vals):.2f} dBSPL")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["drain", "poll", "knob", "mic"])
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()

    dev = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
    with dev:
        sg = sam.SAMGroup(transport.USBTransport(dev))
        sam.USBAdapter(sg)
        print("== discovering ==")
        mons = [m for m in sg.discover_monitors(all=True) if m.address != 1]
        addrs = [1] + [m.address for m in mons]
        print(f"  addresses: {addrs}\n")
        drain(dev, 100, "post-discovery")

        {"drain": lambda: phase_drain(dev, args.seconds),
         "poll": lambda: phase_poll(dev, addrs, args.rounds),
         "knob": lambda: phase_knob(dev, args.seconds),
         "mic": lambda: phase_mic(dev, args.seconds)}[args.phase]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
