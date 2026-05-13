"""Unit tests for Fernet encryption round-trip from SPEC.md Section 3b.5.

Tests:
1. Fernet encrypts and decrypts back to the original plaintext.
2. Different keys produce different ciphertext (semantic security).
3. Tampered ciphertext raises an exception.
"""

import pytest
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet(key: str) -> Fernet:
    """Create a Fernet instance from a base64-encoded key."""
    return Fernet(key.encode())


def test_fernet_round_trip() -> None:
    """Encrypting then decrypting returns the original plaintext."""
    key = Fernet.generate_key().decode()
    f = _get_fernet(key)
    plaintext = b"Hello, MindForge!"
    ciphertext = f.encrypt(plaintext)
    decrypted = f.decrypt(ciphertext)
    assert decrypted == plaintext


def test_different_keys_produce_different_ciphertext() -> None:
    """Two encryptions with different keys must produce different ciphertext."""
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()
    plaintext = b"Secret payload"

    f1 = _get_fernet(key1)
    f2 = _get_fernet(key2)

    ct1 = f1.encrypt(plaintext)
    ct2 = f2.encrypt(plaintext)

    assert ct1 != ct2


def test_same_plaintext_different_keys_ciphertext_different() -> None:
    """Even the same plaintext encrypted with different keys is different."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()
    msg = b"same-text-payload"

    f_a = _get_fernet(key_a)
    f_b = _get_fernet(key_b)

    assert f_a.encrypt(msg) != f_b.encrypt(msg)


def test_tampered_ciphertext_raises_invalid_token() -> None:
    """Modifying the ciphertext causes decryption to raise InvalidToken."""
    key = Fernet.generate_key().decode()
    f = _get_fernet(key)
    ciphertext = f.encrypt(b"original message")

    # Flip a byte in the ciphertext
    tampered = bytearray(ciphertext)
    tampered[10] ^= 0xFF
    tampered_bytes = bytes(tampered)

    with pytest.raises(InvalidToken):
        f.decrypt(tampered_bytes)


def test_wrong_key_raises_invalid_token() -> None:
    """Decrypting with a different key raises InvalidToken."""
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    f1 = _get_fernet(key1)
    f2 = _get_fernet(key2)

    ciphertext = f1.encrypt(b"private data")

    with pytest.raises(InvalidToken):
        f2.decrypt(ciphertext)


def test_fernet_generated_key_is_valid() -> None:
    """Fernet.generate_key() produces a key that can be used immediately."""
    key = Fernet.generate_key().decode()
    f = Fernet(key.encode())
    # Should not raise
    ciphertext = f.encrypt(b"test")
    decrypted = f.decrypt(ciphertext)
    assert decrypted == b"test"
