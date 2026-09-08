#!/usr/bin/env python3
"""Feasibility smoke test for the genlc <-> GLM adapter path.

Read-only by default: opens the adapter, identifies it, discovers monitors,
and polls them. Nothing is changed on the speakers unless --write is passed.
"""
import argparse
import sys
import time

sys.path.insert(0, "genlc/src")

import hid  # noqa: E402
from genlc import const, sam, transport  # noqa: E402
from genlc.gnet import GNetTimeoutException  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="also exercise wakeup + a volume set (audible!)")
    ap.add_argument("--volume", type=float, default=None,
                    help="dB value to set when --write is given, e.g. -30")
    args = ap.parse_args()

    print("== opening GLM adapter ==")
    dev = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
    with dev:
        print(f"  manufacturer : {dev.manufacturer}")
        print(f"  product      : {dev.product}")
        print(f"  serial       : {dev.serial}")

        sg = sam.SAMGroup(transport.USBTransport(dev))
        adapter = sam.USBAdapter(sg)

        print("== adapter queries ==")
        for label, fn in (
            ("hardware", adapter.query_hardware),
            ("software", adapter.query_software),
            ("barcode", adapter.query_barcode),
            ("mic serial", adapter.query_mic_serial),
        ):
            try:
                print(f"  {label:11}: {fn()}")
            except Exception as e:  # noqa: BLE001
                print(f"  {label:11}: FAILED ({type(e).__name__}: {e})")

        print("== discovering monitors (RACE) ==")
        t0 = time.monotonic()
        monitors = [m for m in sg.discover_monitors(all=True) if m.address != 1]
        print(f"  took {time.monotonic() - t0:.2f}s, found {len(monitors)}")

        for m in monitors:
            try:
                hw = m.query_hardware()
                sw = m.query_software()
                bc = m.query_barcode()
            except GNetTimeoutException as e:
                print(f"  [{m.address}] TIMEOUT: {e}")
                continue
            print(f"  [{m.address}] {hw[0]}  serial #{m.serial}")
            print(f"        barcode  : {bc}")
            print(f"        software : {sw}")

        print("== polling (5 rounds, ~0.5s apart) ==")
        for i in range(5):
            row = []
            for m in [adapter] + monitors:
                try:
                    f = m.poll()
                except GNetTimeoutException:
                    row.append(f"[{m.address}] timeout")
                    continue
                if f:
                    row.append(f"[{m.address}] " + " ".join(
                        f"{k}={v:.2f}" for k, v in f.items()))
            print(f"  {i}: " + " | ".join(row))
            time.sleep(0.5)

        if args.write:
            print("== wakeup ==")
            sg.wakeup_all()
            time.sleep(1.0)
            if args.volume is not None:
                print(f"== set volume {args.volume} dB ==")
                list(sg.discover_monitors())
                sg.set_volume_glm(args.volume)

        print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
