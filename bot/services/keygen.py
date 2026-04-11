import base64
import secrets
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from bot.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_x25519_keypair() -> tuple[str, str]:
    private_key = X25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    private_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode()
    public_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode()
    return private_b64, public_b64


def generate_short_id(length: int = 8) -> str:
    return secrets.token_hex(length // 2)


def generate_short_ids(count: int = 6) -> list[str]:
    lengths = [2, 4, 4, 6, 8, 8, 10, 14]
    return [generate_short_id(lengths[i % len(lengths)]) for i in range(count)]


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def generate_ssh_keypair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.OpenSSH,
        encryption_algorithm=NoEncryption(),
    ).decode()
    public_openssh = private_key.public_key().public_bytes(
        encoding=Encoding.OpenSSH,
        format=PublicFormat.OpenSSH,
    ).decode()
    return private_pem, public_openssh
