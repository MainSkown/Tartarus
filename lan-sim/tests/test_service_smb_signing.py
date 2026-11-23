"""SMB2 signing: checked against impacket's client-side code, which Windows interoperates with."""

import hashlib
import hmac
import random

import pytest
from impacket import crypto

from lan_sim.services.smb_signing import (
    DIALECT_2_0_2,
    DIALECT_2_1,
    DIALECT_3_0,
    DIALECT_3_0_2,
    DIALECT_3_1_1,
    PreauthHash,
    derive_signing_key,
    sign_message,
    signature_matches,
)
from lan_sim.services.smb_wire import FLAG_SIGNED, HEADER_SIZE, Header, pack_message

SESSION_KEY = bytes(range(16))
PREAUTH = hashlib.sha512(b"transcript").digest()


def a_message(payload: bytes = b"payload") -> bytes:
    return pack_message(Header(command=5, flags=FLAG_SIGNED, message_id=3), payload)


def zeroed_signature(message: bytes) -> bytes:
    return message[:48] + bytes(16) + message[HEADER_SIZE:]


def test_the_2x_key_is_the_session_key_and_signs_with_hmac_sha256():
    key = derive_signing_key(DIALECT_2_1, SESSION_KEY, b"")
    assert key == SESSION_KEY
    signed = sign_message(DIALECT_2_1, key, a_message())
    expected = hmac.new(key, zeroed_signature(signed), hashlib.sha256).digest()[:16]
    assert signed[48:64] == expected


def test_the_30_key_uses_the_aes_cmac_label_and_the_fixed_context():
    key = derive_signing_key(DIALECT_3_0, SESSION_KEY, b"")
    assert key == crypto.KDF_CounterMode(SESSION_KEY, b"SMB2AESCMAC\x00", b"SmbSign\x00", 128)
    assert derive_signing_key(DIALECT_3_0_2, SESSION_KEY, b"") == key


def test_the_311_key_uses_the_preauth_hash_as_its_context():
    key = derive_signing_key(DIALECT_3_1_1, SESSION_KEY, PREAUTH)
    assert key == crypto.KDF_CounterMode(SESSION_KEY, b"SMBSigningKey\x00", PREAUTH, 128)
    assert key != derive_signing_key(DIALECT_3_1_1, SESSION_KEY, b"\x01" * 64)


@pytest.mark.parametrize("dialect", [DIALECT_3_0, DIALECT_3_0_2, DIALECT_3_1_1])
def test_3x_signatures_equal_impackets_aes_cmac(dialect):
    key = derive_signing_key(dialect, SESSION_KEY, PREAUTH)
    for size in (0, 1, 15, 16, 17, 200, 4096):
        message = a_message(random.Random(size).randbytes(size))  # noqa: S311
        signed = sign_message(dialect, key, message)
        reference = zeroed_signature(signed)
        assert signed[48:64] == crypto.AES_CMAC(key, reference, len(reference))


@pytest.mark.parametrize("dialect", [DIALECT_2_0_2, DIALECT_2_1, DIALECT_3_0, DIALECT_3_1_1])
def test_a_signed_message_verifies_and_a_changed_one_does_not(dialect):
    key = derive_signing_key(dialect, SESSION_KEY, PREAUTH)
    signed = sign_message(dialect, key, a_message())
    assert signature_matches(dialect, key, signed)
    tampered = signed[:-1] + b"X"
    assert not signature_matches(dialect, key, tampered)
    wrong_key = derive_signing_key(dialect, bytes(16), PREAUTH)
    assert not signature_matches(dialect, wrong_key, signed)


def test_signing_sets_the_signed_flag_and_leaves_the_rest_alone():
    unsigned = pack_message(Header(command=5), b"abc")
    signed = sign_message(DIALECT_2_1, SESSION_KEY, unsigned)
    assert signed[16] & FLAG_SIGNED
    assert signed[:16] == unsigned[:16]
    assert signed[20:48] == unsigned[20:48]
    assert signed[HEADER_SIZE:] == b"abc"


def test_the_preauth_hash_chains_sha512_from_zeros():
    chain = PreauthHash()
    assert chain.value == bytes(64)
    chain.update(b"negotiate")
    chain.update(b"response")
    first = hashlib.sha512(bytes(64) + b"negotiate").digest()
    assert chain.value == hashlib.sha512(first + b"response").digest()


def test_a_session_starts_from_a_copy_of_the_connection_hash():
    connection = PreauthHash()
    connection.update(b"negotiate")
    session = connection.copy()
    session.update(b"session setup")
    assert connection.value == hashlib.sha512(bytes(64) + b"negotiate").digest()
    assert session.value != connection.value
