import pytest
from cryptography.fernet import Fernet


@pytest.fixture(scope="session")
def fernet_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _patch_settings(fernet_key: str, mocker):
    mocker.patch(
        "bot.services.keygen.settings",
        ENCRYPTION_KEY=fernet_key,
    )
    mocker.patch(
        "bot.config.settings",
        ENCRYPTION_KEY=fernet_key,
        BOT_TOKEN="test",
        ADMIN_IDS=[1],
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        BITLAUNCH_API_TOKEN="bl-token",
        BITLAUNCH_HOST_ID=4,
        YANDEX_FOLDER_ID="folder",
        YANDEX_IAM_TOKEN="iam",
        YANDEX_SUBNET_ID="subnet",
        YANDEX_ZONE_ID="ru-central1-a",
        YANDEX_IMAGE_FAMILY="ubuntu-2204-lts",
        HTTPX_VERIFY=False,
        REALITY_SNI="www.microsoft.com",
        XRAY_API_PORT=8080,
        XRAY_RUNTIME="systemd",
    )
