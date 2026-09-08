#!/usr/bin/env python3
"""Measure the two idle timeouts, and whether STAY_ONLINE defeats the first.

  T1  how long an assigned address keeps answering on an idle bus
  T2  how long until a silent monitor resets to unassigned (RACE finds it again)

Discovery happens ONCE. RACE only finds *unassigned* monitors, so re-running it
mid-test finds nothing and proves nothing -- addresses are reused instead.

Read-only apart from CID_STAY_ONLINE, a keepalive broadcast that changes
no settings.
"""
import argparse, sys, time
sys.path.insert(0, "genlc/src")
import hid
from genlc import const, sam, transport
from genlc.gnet import GNetMessage, GNetTimeoutException, GNetException

PKT = 64


def send(dev, addr, cid, data=b""):
    m = GNetMessage(addr, cid, data)
    raw = transport.USBTransport.escape(bytes(m))
    dev.write(bytes((0, 0x80 + len(raw))) + raw)


def read(dev, timeout=500):
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
    return bytes(transport.USBTransport.unescape(
        bytearray().join(s[1:] for s in segs).rstrip(b"\0")))


def probe(dev, addr):
    """-> 'data' | 'ack' | 'timeout' | 'silent'. First two mean alive."""
    send(dev, addr, const.CID_POLL)
    msg = read(dev)
    if msg is None:
        return "silent"
    if len(msg) >= 2 and msg[1] == const.GNET_TIMEOUT:
        return "timeout"
    return "data" if len(msg) > 5 else "ack"


def alive(dev, addrs):
    res = [probe(dev, a) for a in addrs]
    return sum(1 for r in res if r in ("data", "ack")), res


def escalate(dev, addrs, keepalive, ka_ms, cap):
    """Grow the idle gap until the addresses stop answering. Returns (last_ok, first_bad)."""
    gap, last_ok = 0.5, 0.0
    while gap <= cap:
        t0 = time.monotonic()
        while time.monotonic() - t0 < gap:
            if keepalive:
                send(dev, const.GNET_BROADCAST_ADDR, const.CID_STAY_ONLINE)
                time.sleep(ka_ms / 1000)
            else:
                time.sleep(0.05)
        n, res = alive(dev, addrs)
        tag = "OK " if n == len(addrs) else ("PART" if n else "DEAD")
        print(f"    gap {gap:6.1f}s -> {tag} {n}/{len(addrs)}  ({','.join(res)})")
        if n == 0:
            return last_ok, gap
        last_ok = gap
        gap *= 1.6
    return last_ok, None


def wait_for_reset(dev, max_wait=180.0):
    """Poll RACE until a monitor answers again. Returns seconds, or None."""
    print(f"    waiting for monitors to reset to unassigned (max {max_wait:.0f}s)...")
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait:
        try:
            sg = sam.SAMGroup(transport.USBTransport(dev))
            serial = sg.race()
        except (GNetTimeoutException, GNetException):
            time.sleep(2.0)
            continue
        el = time.monotonic() - t0
        print(f"    reset after ~{el:.0f}s (monitor #{serial} answered RACE)")
        return el
    print(f"    still not reset after {max_wait:.0f}s")
    return None


def discover(dev):
    sg = sam.SAMGroup(transport.USBTransport(dev))
    sam.USBAdapter(sg)
    mons = [m for m in sg.discover_monitors(all=True) if m.address != 1]
    return sg, [m.address for m in mons]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=40.0, help="max gap to try")
    ap.add_argument("--keepalive-ms", type=int, default=250)
    a = ap.parse_args()

    dev = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
    with dev:
        sg, addrs = discover(dev)
        if not addrs:
            print("No monitors discovered. They may still be assigned from an\n"
                  "earlier run -- wait ~30-60s for them to reset, then retry.")
            return 1
        print(f"== discovered {addrs} ==\n")

        print("[1] T1: bare idle bus, no keepalive")
        ok, bad = escalate(dev, addrs, False, a.keepalive_ms, a.cap)
        if bad:
            print(f"\n  T1: survives {ok:.1f}s, dead by {bad:.1f}s")
        else:
            print(f"\n  T1: survived every gap up to {a.cap:.0f}s -- no lease expiry")

        if bad:
            print("\n[2] T2: how long until they reset to unassigned")
            wait_for_reset(dev)
            sg, addrs = discover(dev)
            if not addrs:
                print("  could not re-discover; stopping")
                return 1
            print(f"  re-discovered {addrs}")

        print(f"\n[3] does STAY_ONLINE every {a.keepalive_ms}ms prevent it?")
        ok2, bad2 = escalate(dev, addrs, True, a.keepalive_ms, a.cap)
        if bad2:
            print(f"\n  with keepalive: survives {ok2:.1f}s, dead by {bad2:.1f}s")
        else:
            print(f"\n  with keepalive: survived every gap up to {a.cap:.0f}s")

        print("\n== verdict ==")
        if bad and not bad2:
            print(f"  STAY_ONLINE WORKS. Send it every {a.keepalive_ms}ms or faster.")
        elif not bad:
            print("  No lease expiry observed; the LED timeout had another cause.")
        else:
            print("  STAY_ONLINE did not prevent expiry -- the GUI must instead\n"
                  "  keep normal traffic flowing, or re-discover on timeout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
