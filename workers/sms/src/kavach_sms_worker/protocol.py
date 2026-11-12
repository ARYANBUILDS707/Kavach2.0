"""Frames: a 4-byte big-endian length, then that many bytes of UTF-8 JSON (one object).

The same format is implemented in `kavach.models.protocol` on the API side; the two packages live
in separate environments, so each keeps its own small copy and both are tested against the limits
below.
"""

import json
import struct
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 32 * 1024  # 4,096 characters of SMS text is at most 16 KiB of UTF-8
MAX_RESPONSE_BYTES = 4 * 1024
HEADER = struct.Struct(">I")


class ProtocolError(Exception):
    """A frame was truncated, oversized or not a JSON object. Never carries frame content."""


def read_exact(stream: BinaryIO, size: int) -> bytes | None:
    """Exactly `size` bytes, or None on a clean end of stream before the first byte."""
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if remaining == size:
                return None
            raise ProtocolError("truncated frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO, max_bytes: int) -> dict[str, Any] | None:
    """The next frame, or None when the peer closed the stream between frames."""
    header = read_exact(stream, HEADER.size)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length == 0 or length > max_bytes:
        raise ProtocolError("frame size out of bounds")
    body = read_exact(stream, length)
    if body is None:
        raise ProtocolError("truncated frame")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError("frame is not JSON") from None
    if not isinstance(message, dict):
        raise ProtocolError("frame is not an object")
    return message


def encode_frame(message: dict[str, Any], max_bytes: int) -> bytes:
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    data = body.encode("utf-8")
    if len(data) > max_bytes:
        raise ProtocolError("frame too large")
    return HEADER.pack(len(data)) + data


def write_frame(stream: BinaryIO, message: dict[str, Any], max_bytes: int) -> None:
    stream.write(encode_frame(message, max_bytes))
    stream.flush()
