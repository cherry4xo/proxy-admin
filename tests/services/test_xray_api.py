"""Tests for Xray API client.

NOTE: Xray v25+ does NOT support CLI adduser/removeuser commands.
XrayApiClient is now used for monitoring/stats only.
User management is done via NodeService.redeploy_node().
"""

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
async def test_xray_api_client_init(xray: XrayApiClient, mock_ssh):
    """Test XrayApiClient initialization."""
    assert xray._host == "1.2.3.4"
    assert xray._api_port == 8080
    assert xray._ssh is mock_ssh


@pytest.mark.asyncio
async def test_get_stats_not_implemented(xray: XrayApiClient):
    """Test get_stats returns None (not implemented for v25+)."""
    result = await xray.get_stats()
    assert result is None


@pytest.mark.asyncio
async def test_xray_api_no_add_user_method(xray: XrayApiClient):
    """Verify add_user method does NOT exist (removed in v25+)."""
    assert not hasattr(xray, 'add_user')


@pytest.mark.asyncio
async def test_xray_api_no_remove_user_method(xray: XrayApiClient):
    """Verify remove_user method does NOT exist (removed in v25+)."""
    assert not hasattr(xray, 'remove_user')
