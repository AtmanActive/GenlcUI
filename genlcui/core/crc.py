"""CRC-16/GSM, as used by the GNet protocol.

Replaces the `libscrc` dependency, which is a C extension with no wheel for
CPython 3.13 and which needs Python headers to build from source. This is the
only thing genlc needed it for.

    poly=0x1021  init=0x0000  refin=false  refout=false  xorout=0xFFFF
    check("123456789") == 0xCE3C
"""

__all__ = ["gsm16"]

_POLY = 0x1021


def _build_table() -> tuple:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ _POLY) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
        table.append(crc)
    return tuple(table)


_TABLE = _build_table()


def gsm16(data: bytes) -> int:
    """Return the CRC-16/GSM of `data`."""
    crc = 0x0000
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[(crc >> 8) ^ byte]
    return crc ^ 0xFFFF
