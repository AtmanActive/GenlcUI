#!/usr/bin/env python3
"""Restore volume control after the bypass/LED experiment.

  status   read what the monitors report, change nothing
  clear    send bypass value 0 (unmuted, LED green, all bits clear)
  mirror   read the knob and apply it as master volume, continuously.
           This restores working volume control in software even if the
           adapter is no longer applying the pot itself. Clamped for safety.
"""
import argparse, sys, time
sys.path.insert(0, ".")
import hid

from genlcui.core import commands as cid
from genlcui.core.protocol import Request
from genlcui.core.session import Session
from genlcui.core.transport import Transport

GLM_VID, GLM_PID = 0x1781, 0x0E39
SAFETY_MAX_DB = -30.0


def connect():
    dev = hid.Device(GLM_VID, GLM_PID)
    transport = Transport(dev)
    session = Session(transport)
    session.discover()
    return transport, session


def cmd_status(session):
    print("== monitors ==")
    for m in session.monitors.values():
        session.poll_monitor(m)
        print(f"  [{m.address}] {m.display_name} #{m.serial}  {m.temperature_c}C")
        print(f"        tags: " + ", ".join(
            f"0x{t:02x}={v}" for t, v in sorted(m.tags.items())))
    session.poll_adapter()
    print(f"\n  knob reads {session.adapter.knob_db} dBFS")
    print("  (if this tracks the pot, the hardware is fine and only the\n"
          "   application of the value is missing)")


def cmd_clear(session):
    print("== clearing bypass state on all monitors ==")
    for m in session.monitors.values():
        for value in (0x00,):
            session.transport.request(
                Request(m.address, cid.CID_BYPASS_QUERY, bytes((value,))))
            print(f"  [{m.address}] {m.display_name}: bypass <- 0x{value:02x}")
        m.muted, m.led_colour = False, "green"
    print("\n  LEDs should now be green and unmuted.")
    print("  Try the knob. If it still does nothing, unplug and replug the")
    print("  GLM adapter's USB cable, which resets it to standalone master.")


def cmd_mirror(session, max_db):
    print(f"== knob -> volume mirror (clamped to {max_db:.0f} dBFS) ==")
    print("   Turn the knob; volume should follow. Ctrl-C to stop.\n")
    last = None
    try:
        while True:
            session.heartbeat()
            session.poll_adapter()
            knob = session.adapter.knob_db
            if knob is not None and knob != last:
                target = min(knob, max_db)
                session.set_volume(target)
                clamp = "  (clamped)" if target != knob else ""
                print(f"  knob {knob:7.1f} -> volume {target:7.1f} dBFS{clamp}")
                last = knob
            time.sleep(cid.ADAPTER_POLL_INTERVAL_S)
    except KeyboardInterrupt:
        print("\n  stopped")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "clear", "mirror"])
    ap.add_argument("--max-db", type=float, default=SAFETY_MAX_DB)
    a = ap.parse_args()
    if a.max_db > SAFETY_MAX_DB:
        print(f"REFUSING: --max-db above the {SAFETY_MAX_DB} dBFS agreed limit.")
        return 1

    transport, session = connect()
    try:
        {"status": lambda: cmd_status(session),
         "clear": lambda: cmd_clear(session),
         "mirror": lambda: cmd_mirror(session, a.max_db)}[a.action]()
    finally:
        transport.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
