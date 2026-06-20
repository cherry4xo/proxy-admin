import pytest

from bot.database.models import Certificate
from bot.services.cert_service import CertService


@pytest.fixture()
def session_factory(mocker):
    return mocker.Mock()


@pytest.fixture()
def mock_session(mocker):
    session = mocker.AsyncMock()
    session.__aenter__ = mocker.AsyncMock(return_value=session)
    session.__aexit__ = mocker.AsyncMock(return_value=False)
    return session


def _scalar_result(mocker, value):
    result = mocker.Mock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


@pytest.fixture()
def service(session_factory) -> CertService:
    return CertService(session_factory=session_factory)


@pytest.mark.asyncio
async def test_get_cert_returns_decrypted(service, session_factory, mock_session, mocker):
    from bot.services.keygen import encrypt

    cert = Certificate(
        domain="pr.cherry4xo.ru",
        fullchain_encrypted=encrypt("FULL"),
        privkey_encrypted=encrypt("KEY"),
    )
    mock_session.execute.return_value = _scalar_result(mocker, cert)
    session_factory.return_value = mock_session

    result = await service.get_cert("pr.cherry4xo.ru")

    assert result == ("FULL", "KEY")


@pytest.mark.asyncio
async def test_ensure_cert_raises_when_absent(service, session_factory, mock_session, mocker):
    mock_session.execute.return_value = _scalar_result(mocker, None)
    session_factory.return_value = mock_session

    with pytest.raises(RuntimeError, match="Нет сертификата"):
        await service.ensure_cert("pr.cherry4xo.ru")


@pytest.mark.asyncio
async def test_store_cert_rejects_invalid_pem(service, session_factory, mock_session, mocker):
    session_factory.return_value = mock_session

    with pytest.raises(ValueError, match="валидный PEM"):
        await service.store_cert("pr.cherry4xo.ru", "not-a-cert", "not-a-key")


@pytest.mark.asyncio
async def test_store_cert_inserts_new(service, session_factory, mock_session, mocker):
    from datetime import datetime

    mock_session.execute.return_value = _scalar_result(mocker, None)
    mock_session.add = mocker.Mock()
    mock_session.commit = mocker.AsyncMock()
    mock_session.refresh = mocker.AsyncMock()
    session_factory.return_value = mock_session
    # Подменяем парсинг X.509 на фиктивную дату — валидный «серт».
    mocker.patch.object(CertService, "_parse_expiry", return_value=datetime(2030, 1, 1))

    await service.store_cert("pr.cherry4xo.ru", "FULLPEM", "KEYPEM")

    mock_session.add.assert_called_once()
