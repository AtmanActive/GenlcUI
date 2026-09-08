#!/usr/bin/env python3
"""Exercise genlcui.core against real hardware. Read-only.

Runs the full stack -- our transport, our protocol decode, our session with
its keepalive heartbeat -- and prints live status for 15 seconds.
"""
import sys, time
sys.path.insert(0, ".")
import hid

from genlcui.core import commands as cid
from genlcui.core.protocol import ADAPTER_ADDR
from genlcui.core.session import Session
from genlcui.core.transport import Transport

GLM_VID, GLM_PID = 0x1781, 0x0E39


def main():
    events = []
    dev = hid.Device(GLM_VID, GLM_PID)
    transport = Transport(dev)
    session = Session(transport, on_event=lambda n, p: events.append(n))

    print("== identifying adapter ==")
    a = session.identify_adapter()
    print(f"  software   : {a.software}")
    print(f"  barcode    : {a.barcode}")
    print(f"  mic serial : {a.mic_serial}  (microphone attached: {a.has_microphone})")

    print("\n== discovering ==")
    t0 = time.monotonic()
    found = session.discover()
    print(f"  {len(found)} monitor(s) in {time.monotonic()-t0:.3f}s")
    for m in session.monitors.values():
        role = "SUB" if m.is_subwoofer else "MAIN"
        print(f"  [{m.address}] {m.display_name:8} #{m.serial}  {role}")
        print(f"        {m.software}")

    print("\n== live status, 15s (heartbeat running) ==")
    t0 = time.monotonic()
    last_monitor_poll = 0.0
    empty_acks = fresh = 0
    while time.monotonic() - t0 < 15.0:
        session.heartbeat()
        session.poll_adapter()
        now = time.monotonic()
        if now - last_monitor_poll >= cid.MONITOR_POLL_INTERVAL_S:
            last_monitor_poll = now
            temps = []
            for m in list(session.monitors.values()):
                got = session.poll_monitor(m)
                if got is None:
                    empty_acks += 1
                else:
                    fresh += 1
                temps.append(f"{m.display_name}:{m.temperature_c}C")
            knob = session.adapter.knob_db
            mic = session.adapter.mic_raw
            print(f"  +{now-t0:5.1f}s  knob={knob:7.1f} dBFS  mic_raw={mic:<9} "
                  f"{' '.join(temps)}")
        time.sleep(cid.ADAPTER_POLL_INTERVAL_S)

    print(f"\n  monitor polls: {fresh} fresh, {empty_acks} empty-ack (rate limited)")
    print(f"  knob_moved events: {events.count('knob_moved')}")
    print("\nOK -- core stack works against real hardware.")
    transport.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
