import pytest
import httpx

from bot.services.cloud.bitlaunch import BitLaunchClient


@pytest.fixture()
def client() -> BitLaunchClient:
    return BitLaunchClient(api_token="test-token", host_id=4, verify_ssl=False)


@pytest.fixture()
def mock_http(mocker):
    return mocker.patch.object(BitLaunchClient, "_client")


def _make_response(mocker, json_data: dict | list, status_code: int = 200) -> httpx.AsyncClient:
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = mocker.Mock()
    mock_resp.status_code = status_code

    mock_async_client = mocker.AsyncMock()
    mock_async_client.__aenter__ = mocker.AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_async_client.get = mocker.AsyncMock(return_value=mock_resp)
    mock_async_client.post = mocker.AsyncMock(return_value=mock_resp)
    mock_async_client.delete = mocker.AsyncMock(return_value=mock_resp)
    return mock_async_client


@pytest.mark.asyncio
async def test_list_servers_returns_list(client: BitLaunchClient, mocker):
    servers = [{"id": "s1", "name": "exit-01", "ipv4": "1.2.3.4", "status": "active"}]
    mock_async_client = _make_response(mocker, {"servers": servers})
    mocker.patch.object(client, "_client", return_value=mock_async_client)

    result = await client.list_servers()

    assert result == servers


@pytest.mark.asyncio
async def test_list_servers_handles_bare_list(client: BitLaunchClient, mocker):
    servers = [{"id": "s1"}]
    mock_async_client = _make_response(mocker, servers)
    mocker.patch.object(client, "_client", return_value=mock_async_client)

    result = await client.list_servers()

    assert result == servers


@pytest.mark.asyncio
async def test_create_server_sends_correct_payload(client: BitLaunchClient, mocker):
    mock_async_client = _make_response(mocker, {"id": "srv-1"})
    mocker.patch.object(client, "_client", return_value=mock_async_client)

    await client.create_server(
        name="exit-01",
        image_id="10000",
        size_id="nibble-1024",
        region_id="lon1",
        ssh_key_ids=["key-1"],
        init_script="#!/bin/bash",
    )

    call_kwargs = mock_async_client.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["hostID"] == 4
    assert payload["name"] == "exit-01"
    assert payload["sshKeys"] == ["key-1"]
    assert payload["initscript"] == "#!/bin/bash"


@pytest.mark.asyncio
async def test_create_server_omits_initscript_when_empty(client: BitLaunchClient, mocker):
    mock_async_client = _make_response(mocker, {"id": "srv-1"})
    mocker.patch.object(client, "_client", return_value=mock_async_client)

    await client.create_server(
        name="exit-01",
        image_id="10000",
        size_id="nibble-1024",
        region_id="lon1",
        ssh_key_ids=[],
        init_script="",
    )

    payload = mock_async_client.post.call_args.kwargs["json"]
    assert "initscript" not in payload


@pytest.mark.asyncio
async def test_wait_for_ip_returns_on_second_poll(client: BitLaunchClient, mocker):
    mocker.patch.object(
        client,
        "get_server",
        side_effect=[
            {"id": "s1", "ipv4": None},
            {"id": "s1", "ipv4": "5.6.7.8"},
        ],
    )
    mocker.patch("bot.services.cloud.bitlaunch.asyncio.sleep")

    result = await client.wait_for_ip("s1", timeout=30, poll_interval=10)

    assert result == "5.6.7.8"
    assert client.get_server.call_count == 2


@pytest.mark.asyncio
async def test_wait_for_ip_raises_timeout(client: BitLaunchClient, mocker):
    mocker.patch.object(client, "get_server", return_value={"id": "s1", "ipv4": None})
    mocker.patch("bot.services.cloud.bitlaunch.asyncio.sleep")

    with pytest.raises(TimeoutError, match="s1"):
        await client.wait_for_ip("s1", timeout=0, poll_interval=10)


@pytest.mark.asyncio
async def test_delete_server_calls_delete_endpoint(client: BitLaunchClient, mocker):
    mock_async_client = _make_response(mocker, {})
    mocker.patch.object(client, "_client", return_value=mock_async_client)

    await client.delete_server("srv-99")

    mock_async_client.delete.assert_called_once_with("/servers/srv-99")


@pytest.mark.asyncio
async def test_create_ssh_key_returns_key_dict(client: BitLaunchClient, mocker):
    expected = {"id": "key-1", "name": "bot-key"}
    mock_async_client = _make_response(mocker, expected)
    mocker.patch.object(client, "_client", return_value=mock_async_client)

    result = await client.create_ssh_key("bot-key", "ssh-ed25519 AAAA...")

    assert result == expected
    payload = mock_async_client.post.call_args.kwargs["json"]
    assert payload["publicKey"] == "ssh-ed25519 AAAA..."
