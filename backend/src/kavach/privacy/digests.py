"""Versioned keyed digests (HMAC-SHA256) for subscriber pseudonyms and payload fingerprints.

The active version signs new values; retired versions stay configured so stored digests can
still be compared during a rotation window (API.md "Event requests and receipts").
A keyed digest is a pseudonym, not anonymization: anyone holding the key can test guesses.
"""

import hashlib
import hmac
from collections.abc import Mapping


class UnknownKeyVersion(Exception):
    """A stored digest names a key version that is no longer configured."""


class KeyedDigester:
    def __init__(self, keys: Mapping[str, bytes], active_version: str) -> None:
        if active_version not in keys:
            raise ValueError("The active key version must be configured")
        self._keys = dict(keys)
        self.active_version = active_version

    def digest(self, data: bytes, version: str | None = None) -> bytes:
        key = self._keys.get(version or self.active_version)
        if key is None:
            raise UnknownKeyVersion
        return hmac.new(key, data, hashlib.sha256).digest()

    def matches(self, data: bytes, stored: bytes, version: str) -> bool:
        return hmac.compare_digest(self.digest(data, version), stored)
