"""Argon2id password hashing with a versioned parameter profile and rehash on login."""

import secrets

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError

# Versioned profile: RFC 9106 low-memory Argon2id (t=3, m=64 MiB, p=4). Each encoded hash records
# its own parameters, so changing this profile triggers a rehash at the user's next login.
PASSWORD_PROFILE = profiles.RFC_9106_LOW_MEMORY
MIN_NEW_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


class PasswordService:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher.from_parameters(PASSWORD_PROFILE)
        # Verified against when the username is unknown, so both paths cost one Argon2 run.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, encoded_hash: str | None, password: str) -> bool:
        try:
            matched = self._hasher.verify(encoded_hash or self._dummy_hash, password)
        except (VerificationError, InvalidHashError):
            return False
        return matched and encoded_hash is not None

    def needs_rehash(self, encoded_hash: str) -> bool:
        return self._hasher.check_needs_rehash(encoded_hash)


def validate_new_password(username: str, password: str) -> None:
    """Policy for operator-provisioned passwords; login itself only bounds the length."""
    if not MIN_NEW_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Passwords must be {MIN_NEW_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters"
        )
    if password.lower() == username.lower():
        raise ValueError("The password must differ from the username")
