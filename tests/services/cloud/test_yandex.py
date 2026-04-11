import pytest

from bot.services.cloud.yandex import YandexClient
from bot.services.cloud.yandex_iam import IamTokenProvider


@pytest.fixture()
def iam_provider(mocker) -> IamTokenProvider:
    provider = mocker.Mock(spec=IamTokenProvider)
    provider.get_token = mocker.AsyncMock(return_value="iam-token")
    return provider


@pytest.fixture()
def client(iam_provider: IamTokenProvider) -> YandexClient:
    return YandexClient(
        folder_id="folder-1",
        iam_provider=iam_provider,
        subnet_id="subnet-1",
        zone_id="ru-central1-a",
        image_family="ubuntu-2204-lts",
        verify_ssl=False,
    )


def _make_http_mock(mocker, json_data: dict | list):
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = mocker.Mock()

    mock_async_client = mocker.AsyncMock()
    mock_async_client.__aenter__ = mocker.AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_async_client.get = mocker.AsyncMock(return_value=mock_resp)
    mock_async_client.post = mocker.AsyncMock(return_value=mock_resp)
    mock_async_client.delete = mocker.AsyncMock(return_value=mock_resp)
    return mock_async_client


@pytest.mark.parametrize(
    ("instance_data", "expected_ip"),
    [
        (
            {"networkInterfaces": [{"primaryV4Address": {"oneToOneNat": {"address": "10.0.0.1"}}}]},
            "10.0.0.1",
        ),
        (
            {"networkInterfaces": []},
            None,
        ),
        (
            {},
            None,
        ),
        (
            {"networkInterfaces": [{"primaryV4Address": {}}]},
            None,
        ),
    ],
)
def test_extract_ip(client: YandexClient, instance_data: dict, expected_ip: str | None):
    result = client.extract_ip(instance_data)

    assert result == expected_ip


@pytest.mark.asyncio
async def test_list_instances_returns_list(client: YandexClient, mocker):
    instances = [{"id": "vm-1", "name": "bridge-01", "status": "RUNNING"}]
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=_make_http_mock(mocker, {"instances": instances})))

    result = await client.list_instances()

    assert result == instances


@pytest.mark.asyncio
async def test_list_instances_returns_empty_on_missing_key(client: YandexClient, mocker):
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=_make_http_mock(mocker, {})))

    result = await client.list_instances()

    assert result == []


@pytest.mark.asyncio
async def test_wait_for_operation_returns_on_done(client: YandexClient, mocker):
    op = {"done": True, "response": {"id": "vm-1"}}
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=_make_http_mock(mocker, op)))

    result = await client.wait_for_operation("op-1")

    assert result == op


@pytest.mark.asyncio
async def test_wait_for_operation_raises_on_error(client: YandexClient, mocker):
    op = {"done": True, "error": {"code": 5, "message": "not found"}}
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=_make_http_mock(mocker, op)))

    with pytest.raises(RuntimeError, match="not found"):
        await client.wait_for_operation("op-1")


@pytest.mark.asyncio
async def test_wait_for_operation_raises_timeout(client: YandexClient, mocker):
    op = {"done": False}
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=_make_http_mock(mocker, op)))
    mocker.patch("bot.services.cloud.yandex.asyncio.sleep")

    with pytest.raises(TimeoutError, match="op-timeout"):
        await client.wait_for_operation("op-timeout", timeout=0, poll_interval=10)


@pytest.mark.asyncio
async def test_wait_for_instance_ip_returns_on_ready(client: YandexClient, mocker):
    instance_with_ip = {"networkInterfaces": [{"primaryV4Address": {"oneToOneNat": {"address": "1.2.3.4"}}}]}
    mocker.patch.object(client, "get_instance", mocker.AsyncMock(return_value=instance_with_ip))
    mocker.patch("bot.services.cloud.yandex.asyncio.sleep")

    result = await client.wait_for_instance_ip("vm-1")

    assert result == "1.2.3.4"


@pytest.mark.asyncio
async def test_wait_for_instance_ip_raises_timeout(client: YandexClient, mocker):
    mocker.patch.object(client, "get_instance", mocker.AsyncMock(return_value={"networkInterfaces": []}))
    mocker.patch("bot.services.cloud.yandex.asyncio.sleep")

    with pytest.raises(TimeoutError, match="vm-timeout"):
        await client.wait_for_instance_ip("vm-timeout", timeout=0, poll_interval=10)


@pytest.mark.asyncio
async def test_create_instance_sends_image_family(client: YandexClient, mocker):
    mock_http = _make_http_mock(mocker, {"id": "op-1"})
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=mock_http))

    await client.create_instance(name="bridge-01", ssh_public_key="ssh-ed25519 AAAA")

    payload = mock_http.post.call_args.kwargs["json"]
    disk_spec = payload["bootDiskSpec"]["diskSpec"]
    assert disk_spec["imageSpec"]["imageFamily"] == "ubuntu-2204-lts"
    assert disk_spec["imageSpec"]["imageFolderId"] == "standard-images"


@pytest.mark.asyncio
async def test_delete_instance_calls_delete_endpoint(client: YandexClient, mocker):
    mock_http = _make_http_mock(mocker, {})
    mocker.patch.object(client, "_client", mocker.AsyncMock(return_value=mock_http))

    await client.delete_instance("vm-99")

    assert "vm-99" in mock_http.delete.call_args.args[0]


@pytest.mark.asyncio
async def test_client_uses_iam_token_in_auth_header(client: YandexClient, iam_provider: IamTokenProvider, mocker):
    captured_kwargs: dict = {}

    def fake_async_client(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return _make_http_mock(mocker, {"instances": []})

    mocker.patch("bot.services.cloud.yandex.httpx.AsyncClient", side_effect=fake_async_client)

    await client._client()

    iam_provider.get_token.assert_called_once()
    assert captured_kwargs.get("headers", {}).get("Authorization") == "Bearer iam-token"
