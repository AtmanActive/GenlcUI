"""GNet wire protocol: framing, encoding, and response decoding.

Extends what genlc implements, with three corrections established by live
capture against real hardware (see docs/PROTOCOL.md):

1. Monitor poll responses are tag-value encoded, not fixed-offset. Upstream's
   fixed offsets read tag bytes as measurements and produce impossible values.
2. The adapter's poll response carries the volume potentiometer position,
   which upstream does not parse at all.
3. Byte 0 of a response is always 0x01 and is NOT a source address, so
   responses cannot be attributed to a device. Ordering is the only
   correlation available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .crc import gsm16

__all__ = [
    "GNET_TERM", "GNET_ACK", "GNET_TIMEOUT", "BROADCAST_ADDR",
    "MULTICAST_ADDR", "ADAPTER_ADDR", "MAX_PACKET_LEN",
    "ProtocolError", "ChecksumError", "DeviceTimeout",
    "escape", "unescape", "Request", "Response",
    "decode_tlv", "AdapterStatus", "decode_adapter_status",
    "MonitorStatus", "decode_monitor_status",
]

GNET_TERM = 0x7E
GNET_ACK = 0x09
GNET_TIMEOUT = 0x7E          # same byte value as TERM, but in the code position

BROADCAST_ADDR = 0xFF
MULTICAST_ADDR = 0xF0
ADAPTER_ADDR = 0x01

MAX_PACKET_LEN = 64

# Tags carrying temperature in degrees C. Which one appears varies by model:
# the 7350A emits 0x41/0x83, the 8330A emits 0x41/0x81/0x83.
TAG_TEMPERATURE = (0x41, 0x81, 0x83)

# Adapter poll payload layout (fixed, NOT tag-value encoded)
_MIC_SLICE = slice(3, 6)         # sint24
_VOLUME_SLICE = slice(15, 19)    # sint32, tenths of a dBFS

VOLUME_MIN_DB = -130.0
VOLUME_MAX_DB = 0.0


class ProtocolError(Exception):
    """Any malformed or unexpected GNet message."""


class ChecksumError(ProtocolError):
    """Response CRC did not match its payload."""


class DeviceTimeout(ProtocolError):
    """The adapter reports that the addressed device did not answer.

    Not a USB-level timeout: the adapter answered us promptly to say the
    device on the RS-485 side stayed silent.
    """


def escape(msg: bytes) -> bytes:
    """Apply PPP byte stuffing to everything before the terminator."""
    if not msg or msg[-1] != GNET_TERM:
        raise ProtocolError("message must end with the terminator byte")
    body = bytes(msg[:-1]).replace(b"\x7d", b"\x7d\x5d").replace(b"\x7e", b"\x7d\x5e")
    return body + bytes((GNET_TERM,))


def unescape(msg: bytes) -> bytes:
    """Reverse PPP byte stuffing."""
    return bytes(msg).replace(b"\x7d\x5e", b"\x7e").replace(b"\x7d\x5d", b"\x7d")


@dataclass(frozen=True)
class Request:
    """An outgoing GNet message."""

    address: int
    command: int
    data: bytes = b""

    def encode(self) -> bytes:
        """address + command + data + CRC16/GSM + terminator."""
        body = bytes((self.address, self.command)) + bytes(self.data)
        return body + gsm16(body).to_bytes(2, "big") + bytes((GNET_TERM,))

    def usb_frame(self) -> bytes:
        """The escaped message with the adapter's 2-byte USB HID prefix."""
        esc = escape(self.encode())
        return bytes((0x00, 0x80 + len(esc))) + esc


@dataclass(frozen=True)
class Response:
    """A decoded GNet response.

    `raw` is the reassembled, unescaped message. `payload` excludes the
    leading marker and code bytes and the trailing CRC and terminator.
    """

    raw: bytes
    code: int
    payload: bytes

    @property
    def is_empty_ack(self) -> bool:
        """True for a bare ACK, which means "nothing new since your last poll".

        Monitors refresh measurements roughly once a second and answer with
        this in between. It is a rate limit, not an error or a dropout.
        """
        return not self.payload

    @classmethod
    def decode(cls, raw: bytes, *, verify_crc: bool = True) -> "Response":
        raw = bytes(raw)
        if len(raw) < 5:
            raise ProtocolError(f"response too short: {raw!r}")
        if raw[-1] != GNET_TERM:
            raise ProtocolError(f"response does not end with terminator: {raw!r}")

        code = raw[1]
        if code == GNET_TIMEOUT:
            raise DeviceTimeout("addressed device did not answer the adapter")
        if code != GNET_ACK:
            raise ProtocolError(f"unexpected response code 0x{code:02x}")

        if verify_crc:
            want = int.from_bytes(raw[-3:-1], "big")
            got = gsm16(raw[:-3])
            if want != got:
                raise ChecksumError(
                    f"checksum 0x{want:04x} != computed 0x{got:04x} "
                    f"for payload {raw[:-3]!r}"
                )
        return cls(raw=raw, code=code, payload=raw[2:-3])


def decode_tlv(payload: bytes) -> Dict[int, int]:
    """Decode a monitor poll payload into {tag: value}.

    Encoding: a tag byte with bit 7 set is followed by a 2-byte big-endian
    value, otherwise by a single byte. Verified to consume payloads exactly
    across differing lengths and models.

    Raises ProtocolError if the stream does not consume cleanly, which is the
    signal that the message was misframed rather than merely unfamiliar.
    """
    out: Dict[int, int] = {}
    i = 0
    while i < len(payload):
        tag = payload[i]
        width = 2 if tag & 0x80 else 1
        if i + 1 + width > len(payload):
            raise ProtocolError(
                f"truncated tag 0x{tag:02x} at offset {i} in {payload!r}"
            )
        out[tag] = int.from_bytes(payload[i + 1:i + 1 + width], "big")
        i += 1 + width
    return out


def _signed(value: int, width_bits: int) -> int:
    limit = 1 << (width_bits - 1)
    return value - (limit << 1) if value >= limit else value


@dataclass(frozen=True)
class MonitorStatus:
    """Decoded monitor poll data. Unknown tags are preserved verbatim."""

    temperature_c: Optional[int]
    tags: Dict[int, int]

    @property
    def unknown_tags(self) -> Dict[int, int]:
        return {t: v for t, v in self.tags.items() if t not in TAG_TEMPERATURE}


def decode_monitor_status(payload: bytes) -> MonitorStatus:
    tags = decode_tlv(payload)
    temp = next((tags[t] for t in TAG_TEMPERATURE if t in tags), None)
    return MonitorStatus(temperature_c=temp, tags=tags)


@dataclass(frozen=True)
class AdapterStatus:
    """Decoded adapter poll data.

    `volume_db` is the physical potentiometer position. Software writes do
    NOT move it, so it reflects only where the knob is: treat a *change* in
    this value as the user grabbing the knob.
    """

    volume_db: Optional[float]
    mic_raw: Optional[int]

    @property
    def has_volume(self) -> bool:
        return self.volume_db is not None


def decode_adapter_status(payload: bytes) -> AdapterStatus:
    mic = None
    if len(payload) >= _MIC_SLICE.stop:
        mic = int.from_bytes(payload[_MIC_SLICE], "big", signed=True)

    volume = None
    if len(payload) >= _VOLUME_SLICE.stop:
        tenths = int.from_bytes(payload[_VOLUME_SLICE], "big", signed=True)
        db = tenths / 10.0
        # Guard against a misframed read presenting as an absurd level.
        if VOLUME_MIN_DB <= db <= VOLUME_MAX_DB:
            volume = db
    return AdapterStatus(volume_db=volume, mic_raw=mic)
