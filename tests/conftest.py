import pytest
from cryptography.fernet import Fernet


@pytest.fixture(scope="session")
def fernet_key() -> str:
    return Fernet.generate_key().decode()


_SETTINGS_OVERRIDES = {
    "BOT_TOKEN": "test",
    "ADMIN_IDS": [1],
    "BITLAUNCH_API_TOKEN": "bl-token",
    "BITLAUNCH_HOST_ID": 4,
    "YANDEX_FOLDER_ID": "folder",
    "YANDEX_SUBNET_ID": "subnet",
    "YANDEX_ZONE_ID": "ru-central1-a",
    "YANDEX_IMAGE_FAMILY": "ubuntu-2204-lts",
    "HTTPX_VERIFY": False,
    "REALITY_SNI": "dl.google.com",
    "FINGERPRINT": "chrome",
    "XHTTP_HOST": "",
    "XRAY_API_PORT": 8080,
    "XRAY_RUNTIME": "systemd",
    "XRAY_VERSION": "v25.12.8",
    "WGCF_VERSION": "2.2.22",
    "SUB_HTTP_HOST": "127.0.0.1",
    "SUB_HTTP_PORT": 8008,
    "SUB_URL_BASE": "https://sub.example.com",
    "SUB_UPDATE_INTERVAL_H": 12,
}


@pytest.fixture(autouse=True)
def _patch_settings(fernet_key: str, mocker):
    import bot.config

    mocker.patch(
        "bot.services.keygen.settings",
        ENCRYPTION_KEY=fernet_key,
    )
    # Патчим атрибуты на РЕАЛЬНОМ объекте settings — так все модули, сделавшие
    # `from bot.config import settings`, видят изменения (одна ссылка на объект).
    mocker.patch.object(bot.config.settings, "ENCRYPTION_KEY", fernet_key)
    for key, value in _SETTINGS_OVERRIDES.items():
        mocker.patch.object(bot.config.settings, key, value)
