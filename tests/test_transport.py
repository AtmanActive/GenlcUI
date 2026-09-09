"""Transport framing tests.

Regression coverage for the desync seen during Wake: stale replies to
fire-and-forget broadcasts becoming the next request's answer, and more than
one message arriving in a single HID packet.
"""

import pytest

from genlcui.core.crc import gsm16
from genlcui.core.protocol import (
    GNET_ACK, GNET_TIMEOUT, DeviceTimeout, ChecksumError, Request,
)
from genlcui.core.transport import Transport, TransportError


def frame(payload: bytes, code: int = GNET_ACK) -> bytes:
    body = bytes((0x01, code)) + payload
    return body + gsm16(body).to_bytes(2, "big") + b"\x7e"


def packet(data: bytes) -> bytes:
    return bytes((63,)) + data + b"\x00" * (64 - 1 - len(data))


class Hid:
    """A HID endpoint that answers only what it was asked.

    `reads` are delivered after a write, one packet at a time until a
    terminator completes the message. `pending` is delivered regardless,
    modelling data already sitting in the queue -- a reply to one of the
    fire-and-forget broadcasts, which is what desynchronised the real bus.
    """

    def __init__(self, reads, pending=None):
        self.reads = list(reads)
        self.pending = list(pending or [])
        self.written = []
        self._armed = False

    def write(self, data):
        self.written.append(bytes(data))
        self._armed = True
        return len(data)

    def read(self, size, timeout=None):
        if self.pending:
            return self.pending.pop(0)
        if not self._armed or not self.reads:
            return b""
        item = self.reads.pop(0)
        if 0x7E in item[1:]:
            self._armed = False       # message complete
        return item

    def close(self):
        pass


def test_single_message():
    t = Transport(Hid([packet(frame(b"\x41\x25"))]))
    assert t.request(Request(2, 0x08)).payload == b"\x41\x25"


def test_timeout_code_is_not_mistaken_for_a_terminator():
    """A timeout response carries 0x7E as its code byte, at index 1. Cutting
    at the first 0x7E truncates every one of them."""
    t = Transport(Hid([packet(frame(b"", code=GNET_TIMEOUT))]))
    with pytest.raises(DeviceTimeout):
        t.request(Request(2, 0x08))


def test_two_messages_in_one_packet_yields_the_first():
    """Taking the whole buffer fails the checksum and swallows the reply that
    followed, desynchronising everything after it."""
    both = frame(b"\x41\x25") + frame(b"\x42\x99")
    t = Transport(Hid([packet(both)]))
    assert t.request(Request(2, 0x08)).payload == b"\x41\x25"


def test_message_spanning_two_packets():
    whole = frame(b"\xAA" * 80)
    t = Transport(Hid([bytes((63,)) + whole[:63], packet(whole[63:])]))
    assert t.request(Request(2, 0x08)).payload == b"\xAA" * 80


def test_corrupt_message_reports_a_checksum_error():
    """Not silently skipped: the caller drains and resynchronises on this."""
    corrupt = bytearray(frame(b"\x41\x25"))
    corrupt[-2] ^= 0xFF
    t = Transport(Hid([packet(bytes(corrupt))]))
    with pytest.raises(ChecksumError):
        t.request(Request(2, 0x08))


def test_stale_data_is_drained_before_a_request():
    """The Wake failure: replies to broadcasts sat queued and were handed
    back as the next request's answer."""
    hid = Hid(reads=[packet(frame(b"\x41\x25"))],        # the real answer
              pending=[packet(frame(b"\x99\x99"))])      # stale, must go
    assert Transport(hid).request(Request(2, 0x08)).payload == b"\x41\x25"


def test_several_stale_messages_are_all_cleared():
    hid = Hid(reads=[packet(frame(b"\x41\x25"))],
              pending=[packet(frame(b"\x99\x99")),
                       packet(frame(b"\x88\x88")),
                       packet(frame(b"\x77\x77"))])
    assert Transport(hid).request(Request(2, 0x08)).payload == b"\x41\x25"


def test_silence_raises_rather_than_blocking():
    with pytest.raises(TransportError):
        Transport(Hid([])).request(Request(2, 0x08))


def test_runaway_stream_without_a_terminator_gives_up():
    endless = [bytes((63,)) + b"\xAA" * 63] * 20
    with pytest.raises(TransportError):
        Transport(Hid(endless)).request(Request(2, 0x08))
