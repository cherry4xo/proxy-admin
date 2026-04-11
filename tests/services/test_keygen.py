import base64

import pytest

from bot.services.keygen import (
    decrypt,
    encrypt,
    generate_short_id,
    generate_ssh_keypair,
    generate_uuid,
    generate_x25519_keypair,
)


def test_encrypt_decrypt_roundtrip():
    plaintext = "super-secret-key"

    ciphertext = encrypt(plaintext)
    result = decrypt(ciphertext)

    assert result == plaintext


def test_encrypt_produces_different_ciphertext_each_time():
    plaintext = "same-input"

    first = encrypt(plaintext)
    second = encrypt(plaintext)

    assert first != second


def test_generate_uuid_is_valid_format():
    result = generate_uuid()

    parts = result.split("-")
    assert len(parts) == 5
    assert len(result) == 36


def test_generate_x25519_keypair_returns_base64url_strings():
    private_b64, public_b64 = generate_x25519_keypair()

    private_bytes = base64.urlsafe_b64decode(private_b64 + "==")
    public_bytes = base64.urlsafe_b64decode(public_b64 + "==")
    assert len(private_bytes) == 32
    assert len(public_bytes) == 32


def test_generate_x25519_keypair_unique_each_call():
    first_priv, first_pub = generate_x25519_keypair()
    second_priv, second_pub = generate_x25519_keypair()

    assert first_priv != second_priv
    assert first_pub != second_pub


def test_generate_ssh_keypair_correct_format():
    private_pem, public_openssh = generate_ssh_keypair()

    assert private_pem.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert public_openssh.startswith("ssh-ed25519")


def test_generate_ssh_keypair_unique_each_call():
    first_priv, _ = generate_ssh_keypair()
    second_priv, _ = generate_ssh_keypair()

    assert first_priv != second_priv


@pytest.mark.parametrize(
    ("length", "expected_str_len"),
    [
        (8, 8),
        (4, 4),
        (16, 16),
    ],
)
def test_generate_short_id_length(length: int, expected_str_len: int):
    result = generate_short_id(length)

    assert len(result) == expected_str_len
    assert all(c in "0123456789abcdef" for c in result)
