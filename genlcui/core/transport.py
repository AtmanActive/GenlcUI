"""USB HID transport to the GLM adapter.

Differs from genlc's transport in two ways that matter in a long-running
process: it never asserts on unexpected input (a stray packet should not crash
the application), and reads take an explicit timeout so a wedged bus surfaces
as an error rather than a hang.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Protocol

from . import protocol
from .protocol import DeviceTimeout, ProtocolError, Request, Response

logger = logging.getLogger(__name__)

MAX_SEGMENTS = 8
DEFAULT_TIMEOUT_MS = 500


class HidDevice(Protocol):
    """The subset of hid.Device we use, so tests can substitute a fake."""

    def write(self, data: bytes) -> int: ...
    def read(self, size: int, timeout: Optional[int] = None) -> bytes: ...
    def close(self) -> None: ...


class TransportError(Exception):
    """The adapter itself is unreachable or answered unintelligibly."""


class Transport:
    """Framed request/response over the adapter's HID endpoint.

    Not thread-safe by contract, but guarded by a lock anyway: request and
    response are correlated purely by ordering (responses carry no source
    address), so two interleaved callers would silently swap each other's
    replies. The lock makes that impossible rather than unlikely.
    """

    def __init__(self, device: HidDevice, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._device = device
        self._timeout_ms = timeout_ms
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            try:
                self._device.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                logger.debug("error closing HID device", exc_info=True)

    # -- raw IO ----------------------------------------------------------

    def _read_message(self, timeout_ms: int) -> bytes:
        """Reassemble one message from up to MAX_SEGMENTS HID packets."""
        segments = []
        while True:
            packet = self._device.read(protocol.MAX_PACKET_LEN, timeout_ms)
            if not packet:
                raise TransportError(
                    f"no response from the adapter within {timeout_ms}ms"
                )
            segments.append(bytes(packet))
            # Byte 0 is a per-packet length marker; the payload follows it.
            if bytes(packet)[1:].rstrip(b"\0").endswith(bytes((protocol.GNET_TERM,))):
                break
            if len(segments) >= MAX_SEGMENTS:
                raise TransportError(
                    f"message did not terminate within {MAX_SEGMENTS} packets"
                )
        joined = bytearray().join(s[1:] for s in segments).rstrip(b"\0")
        return protocol.unescape(bytes(joined))

    def drain(self, timeout_ms: int = 5) -> int:
        """Discard anything already queued. Returns how many packets went.

        Used to resynchronise after an error, since a leftover response would
        otherwise be handed to the next unrelated request.
        """
        dropped = 0
        with self._lock:
            while True:
                try:
                    packet = self._device.read(protocol.MAX_PACKET_LEN, timeout_ms)
                except Exception:  # noqa: BLE001
                    break
                if not packet:
                    break
                dropped += 1
                if dropped > 64:
                    break
        if dropped:
            logger.debug("drained %d stale packet(s)", dropped)
        return dropped

    # -- framed IO -------------------------------------------------------

    def send(self, request: Request) -> None:
        """Fire and forget. Used for broadcasts, which are not answered."""
        with self._lock:
            self._device.write(request.usb_frame())

    def request(self, request: Request, *, timeout_ms: Optional[int] = None) -> Response:
        """Send and decode the reply.

        Raises DeviceTimeout if the addressed device stayed silent, which for
        a monitor usually means its address lease expired.
        """
        timeout = self._timeout_ms if timeout_ms is None else timeout_ms
        with self._lock:
            self._device.write(request.usb_frame())
            raw = self._read_message(timeout)
            try:
                return Response.decode(raw)
            except DeviceTimeout:
                # A well-formed message that happens to report the device did
                # not answer. Nothing is stale, so do NOT drain -- doing so
                # would discard the next legitimate response.
                raise
            except ProtocolError:
                # Malformed input leaves us unsure what is still queued.
                self.drain()
                raise
