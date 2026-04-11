from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    BOT_TOKEN: str
    ADMIN_IDS: list[int]

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./proxy.db"

    # Encryption (Fernet) — для SSH private keys и X25519 в БД
    ENCRYPTION_KEY: str

    # BitLaunch
    BITLAUNCH_API_TOKEN: str = ""
    BITLAUNCH_HOST_ID: int = 4  # 4=DigitalOcean

    # Yandex Cloud
    YANDEX_FOLDER_ID: str = ""
    YANDEX_SA_KEY_FILE: str = "sa-key.json"  # путь к файлу service account key
    YANDEX_SUBNET_ID: str = ""
    YANDEX_ZONE_ID: str = "ru-central1-a"
    YANDEX_IMAGE_FAMILY: str = "ubuntu-2204-lts"

    # SSL verification (отключить если корпоративный прокси с self-signed cert)
    HTTPX_VERIFY: bool = True

    # Xray defaults
    REALITY_SNI: str = "www.microsoft.com"
    XRAY_API_PORT: int = 8080
    # "docker" или "systemd" — способ запуска Xray на нодах
    XRAY_RUNTIME: str = "systemd"

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


settings = Settings()
