"""SMB2/3 message signing: the key derivation per dialect, HMAC-SHA256 and AES-CMAC signatures.

Windows' SMB client signs with a key derived from the session key, so a server that cannot derive
the same key is rejected ("Invalid Signature"): see the spike notes, case 3 addendum.
"""

import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.cmac import CMAC
from impacket import crypto

from lan_sim.services.smb_wire import (
    FLAG_SIGNED,
    HEADER_SIZE,
    SIGNATURE_BYTES,
    SIGNATURE_OFFSET,
)

DIALECT_2_0_2 = 0x0202
DIALECT_2_1 = 0x0210
DIALECT_3_0 = 0x0300
DIALECT_3_0_2 = 0x0302
DIALECT_3_1_1 = 0x0311

PREAUTH_HASH_BYTES = 64
KEY_BITS = 128
FLAGS_OFFSET = 16

# The label ends in a NUL that is part of the string; the KDF adds its own separator NUL after it.
_LABEL_3_0 = b"SMB2AESCMAC\x00"
_CONTEXT_3_0 = b"SmbSign\x00"
_LABEL_3_1_1 = b"SMBSigningKey\x00"


class PreauthHash:
    """SMB 3.1.1's running SHA-512 over the negotiate and session setup messages."""

    def __init__(self, value: bytes = bytes(PREAUTH_HASH_BYTES)) -> None:
        self.value = value

    def update(self, message: bytes) -> None:
        self.value = hashlib.sha512(self.value + message).digest()

    def copy(self) -> "PreauthHash":
        return PreauthHash(self.value)


def derive_signing_key(dialect: int, session_key: bytes, preauth_hash: bytes) -> bytes:
    if dialect == DIALECT_3_1_1:
        return bytes(crypto.KDF_CounterMode(session_key, _LABEL_3_1_1, preauth_hash, KEY_BITS))
    if dialect >= DIALECT_3_0:
        return bytes(crypto.KDF_CounterMode(session_key, _LABEL_3_0, _CONTEXT_3_0, KEY_BITS))
    return session_key


def sign_message(dialect: int, key: bytes, message: bytes) -> bytes:
    """`message` with the signed flag set and its signature field filled in."""
    flags = int.from_bytes(message[FLAGS_OFFSET : FLAGS_OFFSET + 4], "little") | FLAG_SIGNED
    prepared = (
        message[:FLAGS_OFFSET]
        + flags.to_bytes(4, "little")
        + message[FLAGS_OFFSET + 4 : SIGNATURE_OFFSET]
        + bytes(SIGNATURE_BYTES)
        + message[HEADER_SIZE:]
    )
    signature = _signature(dialect, key, prepared)
    return prepared[:SIGNATURE_OFFSET] + signature + prepared[HEADER_SIZE:]


def signature_matches(dialect: int, key: bytes, message: bytes) -> bool:
    received = message[SIGNATURE_OFFSET:HEADER_SIZE]
    zeroed = message[:SIGNATURE_OFFSET] + bytes(SIGNATURE_BYTES) + message[HEADER_SIZE:]
    return hmac.compare_digest(received, _signature(dialect, key, zeroed))


def _signature(dialect: int, key: bytes, zeroed_message: bytes) -> bytes:
    if dialect >= DIALECT_3_0:
        mac = CMAC(algorithms.AES(key))
        mac.update(zeroed_message)
        return mac.finalize()
    return hmac.new(key, zeroed_message, hashlib.sha256).digest()[:SIGNATURE_BYTES]
