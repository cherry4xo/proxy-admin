import logging
from datetime import datetime

from cryptography import x509
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.database.models import Certificate
from bot.services.keygen import decrypt, encrypt

logger = logging.getLogger(__name__)


class CertService:
    """Хранение и выдача TLS-сертов доменов.

    Серты выпускаются ВРУЧНУЮ (certbot --manual + TXT в DNS регистратора) и загружаются
    в бота (через Telegram). Здесь — только хранение (Fernet в БД) и выдача для раскладки
    по bridge-нодам. Автоматического ACME-выпуска нет.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _parse_expiry(fullchain_pem: str) -> datetime | None:
        try:
            cert = x509.load_pem_x509_certificate(fullchain_pem.encode())
            return cert.not_valid_after_utc.replace(tzinfo=None)
        except Exception:
            logger.exception("Failed to parse cert expiry")
            return None

    async def store_cert(self, domain: str, fullchain_pem: str, privkey_pem: str) -> Certificate:
        """Сохранить (или обновить) серт домена. Возвращает запись Certificate."""
        # Валидация: должен парситься как X.509.
        if self._parse_expiry(fullchain_pem) is None:
            raise ValueError("fullchain не распознан как валидный PEM-сертификат")
        expires_at = self._parse_expiry(fullchain_pem)

        async with self._session_factory() as session:
            result = await session.execute(
                select(Certificate).where(Certificate.domain == domain)
            )
            cert = result.scalar_one_or_none()
            if cert:
                cert.fullchain_encrypted = encrypt(fullchain_pem)
                cert.privkey_encrypted = encrypt(privkey_pem)
                cert.expires_at = expires_at
            else:
                cert = Certificate(
                    domain=domain,
                    fullchain_encrypted=encrypt(fullchain_pem),
                    privkey_encrypted=encrypt(privkey_pem),
                    expires_at=expires_at,
                )
                session.add(cert)
            await session.commit()
            await session.refresh(cert)
            return cert

    async def get_cert(self, domain: str) -> tuple[str, str] | None:
        """(fullchain_pem, privkey_pem) или None, если серта нет."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Certificate).where(Certificate.domain == domain)
            )
            cert = result.scalar_one_or_none()
        if not cert:
            return None
        return decrypt(cert.fullchain_encrypted), decrypt(cert.privkey_encrypted)

    async def ensure_cert(self, domain: str) -> tuple[str, str]:
        """Вернуть серт домена из БД. Бросает, если серт ещё не загружен.

        Возвращает (fullchain_pem, privkey_pem).
        """
        cert = await self.get_cert(domain)
        if not cert:
            raise RuntimeError(
                f"Нет сертификата для {domain}. Сначала выпусти его вручную "
                f"(certbot --manual, TXT в DNS) и загрузи через «Загрузить сертификат»."
            )
        return cert
