#!/usr/bin/env python3
"""Second-round diagnostics: poll timing, and knob range confirmation.

Read-only apart from STAY_ONLINE (a keepalive broadcast, changes no settings).
"""
import argparse, sys, time
sys.path.insert(0, "genlc/src")
import hid
from genlc import const, sam, transport
from genlc.gnet import GNetMessage

PKT = 64


def hexs(b): return " ".join(f"{x:02x}" for x in b)


def read_msg(dev, timeout):
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


def send(dev, addr, cid, data=b""):
    m = GNetMessage(addr, cid, data)
    raw = transport.USBTransport.escape(bytes(m))
    dev.write(bytes((0, 0x80 + len(raw))) + raw)


def tlv(payload):
    i, out = 0, []
    while i < len(payload):
        t = payload[i]
        n = 2 if t & 0x80 else 1
        if i + 1 + n > len(payload):
            out.append((t, None)); break
        out.append((t, int.from_bytes(payload[i+1:i+1+n], "big")))
        i += 1 + n
    return out, i == len(payload)


def phase_async(dev, addr, tries):
    """Send ONE poll, then keep reading. Does late data arrive?"""
    print(f"== async test: one POLL to addr {addr}, then read for 1s ==")
    for k in range(tries):
        # deliberately do NOT drain
        t0 = time.monotonic()
        send(dev, addr, const.CID_POLL)
        got = 0
        while time.monotonic() - t0 < 1.0:
            msg, _ = read_msg(dev, 100)
            if not msg:
                continue
            got += 1
            body = msg[2:-3]
            kind = "EMPTY ACK" if not body else f"DATA ({len(body)}B)"
            print(f"  try{k} +{(time.monotonic()-t0)*1000:6.1f}ms  #{got}  {kind}  {hexs(msg)}")
        if got == 0:
            print(f"  try{k}  <nothing at all>")
    print("\n  >1 message per request => responses are asynchronous.")


def phase_cadence(dev, addrs, delay_ms):
    """How does inter-poll delay affect the empty-ACK rate?"""
    print(f"== cadence test ==")
    for delay in [0, 20, 50, 100, 250, 500]:
        stats = {a: [0, 0] for a in addrs}   # [data, empty]
        for _ in range(8):
            for a in addrs:
                send(dev, a, const.CID_POLL)
                msg, _ = read_msg(dev, 400)
                if msg is None:
                    continue
                stats[a][0 if len(msg) > 5 else 1] += 1
                if delay:
                    time.sleep(delay / 1000)
        line = "  ".join(f"[{a}] {d}/{d+e}" for a, (d, e) in stats.items())
        print(f"  delay {delay:4d}ms   data/total:  {line}")


def phase_stayonline(dev, addrs):
    print("== does STAY_ONLINE restore poll data? ==")
    for label, keepalive in (("without", False), ("with", True)):
        ok = {a: 0 for a in addrs}
        for _ in range(8):
            if keepalive:
                send(dev, const.GNET_BROADCAST_ADDR, const.CID_STAY_ONLINE)
                time.sleep(0.02)
            for a in addrs:
                send(dev, a, const.CID_POLL)
                msg, _ = read_msg(dev, 400)
                if msg and len(msg) > 5:
                    ok[a] += 1
        print(f"  {label:8} keepalive: " + "  ".join(f"[{a}] {n}/8" for a, n in ok.items()))


def phase_knobrange(dev, seconds):
    print(f"== knob range, {seconds}s ==")
    print("   Turn FULLY counter-clockwise, then FULLY clockwise.")
    print("   Expecting min -1300 (-130.0 dB) and max 0 if the theory holds.\n")
    lo, hi, t0 = 10**9, -10**9, time.monotonic()
    while time.monotonic() - t0 < seconds:
        send(dev, 1, const.CID_POLL)
        msg, _ = read_msg(dev, 300)
        if not msg or len(msg) < 24:
            continue
        v = int.from_bytes(msg[17:21], "big", signed=True)
        if v < lo or v > hi:
            lo, hi = min(lo, v), max(hi, v)
            print(f"  raw={v:6d}   {v/10:8.1f} dB      (range {lo/10:.1f} .. {hi/10:.1f})")
        time.sleep(0.05)
    print(f"\n  FINAL: raw {lo}..{hi}  =>  {lo/10:.1f} dB .. {hi/10:.1f} dB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["async", "cadence", "stayonline", "knobrange"])
    ap.add_argument("--addr", type=int, default=2)
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=20.0)
    a = ap.parse_args()

    dev = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
    with dev:
        sg = sam.SAMGroup(transport.USBTransport(dev))
        sam.USBAdapter(sg)
        mons = [m for m in sg.discover_monitors(all=True) if m.address != 1]
        addrs = [m.address for m in mons]
        print(f"== discovered: {[1]+addrs} ==\n")
        {"async": lambda: phase_async(dev, a.addr, a.tries),
         "cadence": lambda: phase_cadence(dev, addrs, 0),
         "stayonline": lambda: phase_stayonline(dev, addrs),
         "knobrange": lambda: phase_knobrange(dev, a.seconds)}[a.phase]()


if __name__ == "__main__":
    sys.exit(main() or 0)
