"""The fixed, fictional self-test message. Written for this file; not from any dataset, real
message or simulator scenario. Its SHA-256 is pinned in the manifest, so editing it requires a
new manifest version with re-measured expected outputs."""

import hashlib

CANARY_ID = "canary-v1"
CANARY_TEXT = (
    "FICTIONAL SELF-TEST: Your Examplebank account is suspended. Confirm your card number "
    "and PIN within 2 hours at http://examplebank-verify.example to avoid closure."
)


def canary_sha256() -> str:
    return hashlib.sha256(CANARY_TEXT.encode("utf-8")).hexdigest()
