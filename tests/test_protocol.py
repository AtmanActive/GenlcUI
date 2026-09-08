"""Protocol tests.

Every fixture below is a real message captured from the author's rig
(GLM adapter fw 1.3.2.5053, Genelec 7350A + 2x 8330A), not synthesised.
"""

import pytest

from genlcui.core.crc import gsm16
from genlcui.core.protocol import (
    ADAPTER_ADDR, DeviceTimeout, ChecksumError, ProtocolError,
    Request, Response, decode_adapter_status, decode_monitor_status,
    decode_tlv, escape, unescape,
)


def h(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


# Captured responses ------------------------------------------------------

EMPTY_ACK = h("01 09 5d e7 7e")

MONITOR_7350A = h(
    "01 09 41 2d 83 00 2d 42 c9 46 80 43 80 45 92 47 01 49 60 "
    "84 01 61 8a 00 19 40 89 7e")
MONITOR_8330A_a = h(
    "01 09 41 25 81 00 25 83 00 25 42 cb 43 92 45 89 47 01 49 5f "
    "84 02 bf 8a 00 19 8e db 7e")
MONITOR_8330A_b = h(
    "01 09 41 25 81 00 25 83 00 25 42 cc 43 92 45 8a 47 01 49 5f "
    "84 02 bf 8a 00 19 8e b6 7e")

# Adapter poll, knob at -84.3 dBFS
ADAPTER = h(
    "01 09 32 34 de 02 6d ad 00 dd 00 26 fd 43 30 37 df ff ff fc b5 3a f0 7e")
# Adapter poll, knob at -130.0 dBFS (fully counter-clockwise)
ADAPTER_MIN = h(
    "01 09 32 34 de 03 df 20 00 dd 00 17 22 6f 30 37 df ff ff fa ec 80 ea 7e")

ALL_REAL = [EMPTY_ACK, MONITOR_7350A, MONITOR_8330A_a, MONITOR_8330A_b,
            ADAPTER, ADAPTER_MIN]


# CRC ---------------------------------------------------------------------

def test_crc_check_value():
    """The published CRC-16/GSM check value."""
    assert gsm16(b"123456789") == 0xCE3C


@pytest.mark.parametrize("msg", ALL_REAL)
def test_crc_of_captured_messages(msg):
    assert gsm16(msg[:-3]) == int.from_bytes(msg[-3:-1], "big")


# Framing -----------------------------------------------------------------

def test_request_round_trips_through_crc():
    req = Request(ADAPTER_ADDR, 0x08)
    enc = req.encode()
    assert enc[0] == ADAPTER_ADDR and enc[1] == 0x08
    assert enc[-1] == 0x7E
    assert gsm16(enc[:-3]) == int.from_bytes(enc[-3:-1], "big")


def test_usb_frame_has_adapter_prefix():
    frame = Request(0xFF, 0x08).usb_frame()
    assert frame[0] == 0x00
    assert frame[1] == 0x80 + len(frame) - 2


def test_escape_unescape_round_trip():
    body = bytes([0x01, 0x7D, 0x7E, 0x42, 0x7D, 0x7E]) + b"\x7e"
    assert unescape(escape(body)[:-1]) + b"\x7e" == body


def test_escape_requires_terminator():
    with pytest.raises(ProtocolError):
        escape(b"\x01\x02")


# Response decoding -------------------------------------------------------

def test_empty_ack_means_no_new_data():
    r = Response.decode(EMPTY_ACK)
    assert r.is_empty_ack
    assert r.payload == b""


def test_device_timeout_is_distinguished_from_a_bad_message():
    """Code byte 0x7E is the adapter saying the device stayed silent."""
    body = bytes((0x01, 0x7E))
    raw = body + gsm16(body).to_bytes(2, "big") + b"\x7e"
    with pytest.raises(DeviceTimeout):
        Response.decode(raw)


def test_corrupt_checksum_is_rejected():
    bad = bytearray(MONITOR_7350A)
    bad[-2] ^= 0xFF
    with pytest.raises(ChecksumError):
        Response.decode(bytes(bad))


def test_short_message_is_rejected():
    with pytest.raises(ProtocolError):
        Response.decode(b"\x01\x09")


# TLV --------------------------------------------------------------------

@pytest.mark.parametrize("msg", [MONITOR_7350A, MONITOR_8330A_a, MONITOR_8330A_b])
def test_tlv_consumes_payload_exactly(msg):
    """A misframed payload would leave a trailing partial tag."""
    decode_tlv(Response.decode(msg).payload)  # must not raise


def test_tlv_truncated_payload_raises():
    with pytest.raises(ProtocolError):
        decode_tlv(bytes([0x84, 0x01]))       # 16-bit tag, only one byte left


def test_temperature_matches_independently_reported_values():
    """genlc's own poll reported 45 C for the sub and 37 C for the mains."""
    assert decode_monitor_status(
        Response.decode(MONITOR_7350A).payload).temperature_c == 45
    for msg in (MONITOR_8330A_a, MONITOR_8330A_b):
        assert decode_monitor_status(
            Response.decode(msg).payload).temperature_c == 37


def test_models_expose_different_tag_sets():
    """The 7350A emits 0x46 and omits 0x81; the 8330A does the reverse.

    This is why a fixed-offset parser cannot work.
    """
    sub = decode_monitor_status(Response.decode(MONITOR_7350A).payload).tags
    main = decode_monitor_status(Response.decode(MONITOR_8330A_a).payload).tags
    assert 0x46 in sub and 0x46 not in main
    assert 0x81 in main and 0x81 not in sub


# Adapter status ---------------------------------------------------------

def test_volume_pot_decodes_to_tenths_of_a_dbfs():
    assert decode_adapter_status(
        Response.decode(ADAPTER).payload).volume_db == pytest.approx(-84.3)


def test_volume_floor_matches_documented_minimum():
    """GLM 4 documents the fader as 0 dBFS down to -130 dBFS."""
    assert decode_adapter_status(
        Response.decode(ADAPTER_MIN).payload).volume_db == pytest.approx(-130.0)


def test_mic_level_present_when_microphone_attached():
    assert decode_adapter_status(Response.decode(ADAPTER).payload).mic_raw > 0


def test_out_of_range_volume_is_rejected_rather_than_reported():
    """A misframed read must not surface as a plausible-looking level."""
    payload = bytes(15) + (12345).to_bytes(4, "big")
    assert decode_adapter_status(payload).volume_db is None


def test_short_adapter_payload_yields_no_volume():
    assert decode_adapter_status(b"\x00\x01\x02").volume_db is None
