"""API side of the worker frame format: a 4-byte big-endian length, then UTF-8 JSON (one object).

The worker (`workers/sms/src/kavach_sms_worker/protocol.py`) keeps its own copy because the two
packages live in separate environments; both are tested against the same limits.
"""

import json
import struct
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 4 * 1024
HEADER = struct.Struct(">I")


class ProtocolError(Exception):
    """A frame was truncated, oversized or not a JSON object. Never carries frame content."""


def read_exact(stream: BinaryIO, size: int) -> bytes | None:
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
