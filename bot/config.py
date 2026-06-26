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
    # Пин версии Xray-core (детерминированный деплой + гарантия свежей мимикрии
    # NewSessionTicket/uTLS). Менять осознанно, сверяясь с релизами XTLS/Xray-core.
    XRAY_VERSION: str = "v25.12.8"
    # Версия wgcf для генерации WARP-профиля на нодах.
    WGCF_VERSION: str = "2.2.22"
    # Дефолтный REALITY-донор (dest/SNI). Критерии XTLS: TLS1.3+H2, не редирект,
    # IP не в РФ, post-ServerHello шифруется единым блоком (dl.google.com — эталон).
    REALITY_SNI: str = "dl.google.com"
    # uTLS fingerprint для REALITY (chrome|firefox|safari|ios|android|edge|random|randomized).
    # chrome — рекомендация 2026; uTLS в пиновой XRAY_VERSION обновлён под свежий Chrome.
    FINGERPRINT: str = "chrome"
    # HTTP Host заголовок для XHTTP транспорта — должен быть твой домен или IP ноды
    # Если пустой — используется IP ноды автоматически
    XHTTP_HOST: str = ""
    XRAY_API_PORT: int = 8080
    # "docker" или "systemd" — способ запуска Xray на нодах
    XRAY_RUNTIME: str = "systemd"

    # Subscription HTTP-сервер (отдельный docker-контейнер: python -m bot.web.subscription)
    SUB_HTTP_HOST: str = "0.0.0.0"     # внутри контейнера слушаем все интерфейсы
    SUB_HTTP_PORT: int = 8008          # наружу маппится как 127.0.0.1:8008 (через nginx/поддомен)
    SUB_URL_BASE: str = ""             # публичный базовый URL, напр. "https://sub.cherry4xo.ru"
    SUB_UPDATE_INTERVAL_H: int = 12    # Profile-Update-Interval (часы) для клиента

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


settings = Settings()
