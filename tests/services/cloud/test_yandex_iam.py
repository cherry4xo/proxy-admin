import time

import pytest

from bot.services.cloud.yandex_iam import IamTokenProvider, ServiceAccountKey

_FRESH_TOKEN = "t1.fresh-token"
_CACHED_TOKEN = "t1.cached-token"


@pytest.fixture()
def sa_key(mocker) -> ServiceAccountKey:
    key = mocker.Mock(spec=ServiceAccountKey)
    key.create_jwt.return_value = "signed-jwt"
    return key


@pytest.fixture()
def provider(sa_key: ServiceAccountKey) -> IamTokenProvider:
    return IamTokenProvider(sa_key=sa_key, verify_ssl=False)


@pytest.mark.asyncio
async def test_get_token_fetches_new_token_when_expired(provider: IamTokenProvider, sa_key: ServiceAccountKey, mocker):
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"iamToken": _FRESH_TOKEN}
    mock_response.raise_for_status = mocker.Mock()

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(return_value=mock_response)

    mocker.patch("bot.services.cloud.yandex_iam.httpx.AsyncClient", return_value=mock_client)

    result = await provider.get_token()

    assert result == _FRESH_TOKEN
    sa_key.create_jwt.assert_called_once()
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_get_token_returns_cached_token_when_not_expired(provider: IamTokenProvider, mocker):
    provider._token = _CACHED_TOKEN
    provider._expires_at = time.time() + 3000

    mock_post = mocker.patch("bot.services.cloud.yandex_iam.httpx.AsyncClient")

    result = await provider.get_token()

    assert result == _CACHED_TOKEN
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_get_token_refreshes_when_near_expiry(provider: IamTokenProvider, sa_key: ServiceAccountKey, mocker):
    provider._token = _CACHED_TOKEN
    provider._expires_at = time.time() + 30

    mock_response = mocker.Mock()
    mock_response.json.return_value = {"iamToken": _FRESH_TOKEN}
    mock_response.raise_for_status = mocker.Mock()

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__ = mocker.AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_client.post = mocker.AsyncMock(return_value=mock_response)

    mocker.patch("bot.services.cloud.yandex_iam.httpx.AsyncClient", return_value=mock_client)

    result = await provider.get_token()

    assert result == _FRESH_TOKEN
