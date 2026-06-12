import pytest

from bot.services.xray_api import XrayApiClient


@pytest.fixture()
def mock_ssh(mocker):
    ssh = mocker.Mock()
    ssh.run_command = mocker.AsyncMock(return_value=("", ""))
    return ssh


@pytest.fixture()
def xray(mock_ssh) -> XrayApiClient:
    return XrayApiClient(host="1.2.3.4", api_port=8080, ssh_client=mock_ssh)


@pytest.mark.asyncio
async def test_add_user_builds_adduser_command(xray: XrayApiClient, mock_ssh):
    await xray.add_user("inbound-vless", "uuid-1", flow="")

    cmd = mock_ssh.run_command.call_args.args[0]
    assert "xray api adduser" in cmd
    assert "--server=127.0.0.1:8080" in cmd
    assert "-tag=inbound-vless" in cmd
    assert '"id":"uuid-1"' in cmd
    assert '"flow":""' in cmd


@pytest.mark.asyncio
async def test_add_user_raises_on_error_output(xray: XrayApiClient, mock_ssh):
    mock_ssh.run_command.return_value = ("", "error: tag not found")

    with pytest.raises(RuntimeError, match="adduser failed"):
        await xray.add_user("inbound-vless", "uuid-1")


@pytest.mark.asyncio
async def test_remove_user_builds_removeuser_command(xray: XrayApiClient, mock_ssh):
    await xray.remove_user("inbound-vless", "uuid-1")

    cmd = mock_ssh.run_command.call_args.args[0]
    assert "xray api removeuser" in cmd
    assert "-tag=inbound-vless" in cmd
    assert "-email=uuid-1" in cmd
