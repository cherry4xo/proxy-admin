from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.database.models import Node, SSHKey, User
from bot.services.user_service import UserService
from bot.services.xray_api import XrayApiClient


@pytest.fixture()
def session_factory(mocker):
    return mocker.Mock()


@pytest.fixture()
def mock_session(mocker):
    session = mocker.AsyncMock()
    session.__aenter__ = mocker.AsyncMock(return_value=session)
    session.__aexit__ = mocker.AsyncMock(return_value=False)
    return session


@pytest.fixture()
def ssh_key() -> SSHKey:
    key = SSHKey()
    key.id = 1
    key.name = "bot-key"
    key.public_key = "ssh-ed25519 AAAA"
    key.private_key_encrypted = "encrypted-pem"
    key.created_at = datetime.now(timezone.utc)
    return key


@pytest.fixture()
def exit_node(ssh_key: SSHKey) -> Node:
    node = Node()
    node.id = 10
    node.role = "exit"
    node.provider = "bitlaunch"
    node.provider_id = "srv-1"
    node.name = "exit-01"
    node.ip = "1.2.3.4"
    node.ssh_port = 22
    node.ssh_key_id = ssh_key.id
    node.x25519_public = "pubkey"
    node.short_id = "abcd1234"
    node.reality_sni = "www.microsoft.com"
    node.xray_api_port = 8080
    node.status = "active"
    node.created_at = datetime.now(timezone.utc)
    return node


@pytest.fixture()
def active_user(exit_node: Node) -> User:
    user = User()
    user.id = 1
    user.name = "alice"
    user.uuid = "00000000-0000-0000-0000-000000000001"
    user.exit_node_id = exit_node.id
    user.is_active = True
    user.created_at = datetime.now(timezone.utc)
    return user


@pytest.fixture()
def mock_xray(mocker) -> XrayApiClient:
    xray = mocker.Mock(spec=XrayApiClient)
    xray.add_user = mocker.AsyncMock()
    xray.remove_user = mocker.AsyncMock()
    return xray


@pytest.fixture()
def mock_node_service(mocker):
    from bot.services.node_service import NodeService
    svc = mocker.Mock(spec=NodeService)
    svc.redeploy_node = mocker.AsyncMock()
    return svc


@pytest.fixture()
def service(session_factory, mocker, mock_xray: XrayApiClient, mock_node_service) -> UserService:
    svc = UserService(session_factory=session_factory, node_service=mock_node_service)
    mocker.patch.object(svc, "_make_xray_client", return_value=mock_xray)
    return svc


def _make_scalar_result(mocker, value):
    result = mocker.Mock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


@pytest.mark.asyncio
async def test_create_user_saves_user_and_redeploys(
    service: UserService,
    session_factory,
    mock_session,
    exit_node: Node,
    ssh_key: SSHKey,
    mock_node_service,
    mocker,
):
    mock_session.execute.side_effect = [
        _make_scalar_result(mocker, exit_node),
        _make_scalar_result(mocker, ssh_key),
    ]
    mock_session.add = mocker.Mock()
    mock_session.commit = mocker.AsyncMock()
    mock_session.refresh = mocker.AsyncMock()
    session_factory.return_value = mock_session

    user, vless_url, qr_bytes = await service.create_user(name="alice", exit_node_id=10)

    mock_node_service.redeploy_node.assert_called_once_with(10)
    assert "1.2.3.4" in vless_url
    assert len(qr_bytes) > 0


@pytest.mark.asyncio
async def test_create_user_raises_when_node_not_found(
    service: UserService,
    session_factory,
    mock_session,
    mocker,
):
    mock_session.execute.return_value = _make_scalar_result(mocker, None)
    session_factory.return_value = mock_session

    with pytest.raises(ValueError, match="Exit node 99 not found"):
        await service.create_user(name="alice", exit_node_id=99)


@pytest.mark.asyncio
async def test_create_user_raises_when_node_has_no_ip(
    service: UserService,
    session_factory,
    mock_session,
    exit_node: Node,
    ssh_key: SSHKey,
    mocker,
):
    exit_node.ip = None
    mock_session.execute.return_value = _make_scalar_result(mocker, exit_node)
    session_factory.return_value = mock_session

    with pytest.raises(ValueError, match="has no IP"):
        await service.create_user(name="alice", exit_node_id=10)


@pytest.mark.asyncio
async def test_create_user_raises_when_node_role_is_bridge(
    service: UserService,
    session_factory,
    mock_session,
    exit_node: Node,
    mocker,
):
    exit_node.role = "bridge"
    mock_session.execute.return_value = _make_scalar_result(mocker, exit_node)
    session_factory.return_value = mock_session

    with pytest.raises(ValueError, match="not found"):
        await service.create_user(name="alice", exit_node_id=10)


@pytest.mark.asyncio
async def test_deactivate_user_sets_inactive(
    service: UserService,
    session_factory,
    mock_session,
    active_user: User,
    exit_node: Node,
    ssh_key: SSHKey,
    mock_xray: XrayApiClient,
    mocker,
):
    mock_session.execute.side_effect = [
        _make_scalar_result(mocker, active_user),
        _make_scalar_result(mocker, exit_node),
        _make_scalar_result(mocker, ssh_key),
        _make_scalar_result(mocker, active_user),
    ]
    mock_session.commit = mocker.AsyncMock()
    mock_session.delete = mocker.AsyncMock()
    session_factory.return_value = mock_session

    await service.deactivate_user(user_id=1, delete_from_db=False)

    mock_xray.remove_user.assert_called_once_with("inbound-vless", active_user.uuid)
    assert active_user.is_active is False
    mock_session.delete.assert_not_called()


@pytest.mark.asyncio
async def test_deactivate_user_deletes_from_db(
    service: UserService,
    session_factory,
    mock_session,
    active_user: User,
    exit_node: Node,
    ssh_key: SSHKey,
    mock_xray: XrayApiClient,
    mocker,
):
    mock_session.execute.side_effect = [
        _make_scalar_result(mocker, active_user),
        _make_scalar_result(mocker, exit_node),
        _make_scalar_result(mocker, ssh_key),
        _make_scalar_result(mocker, active_user),
    ]
    mock_session.commit = mocker.AsyncMock()
    mock_session.delete = mocker.AsyncMock()
    session_factory.return_value = mock_session

    await service.deactivate_user(user_id=1, delete_from_db=True)

    mock_session.delete.assert_called_once_with(active_user)


@pytest.mark.asyncio
async def test_deactivate_user_raises_when_not_found(
    service: UserService,
    session_factory,
    mock_session,
    mocker,
):
    mock_session.execute.return_value = _make_scalar_result(mocker, None)
    session_factory.return_value = mock_session

    with pytest.raises(ValueError, match="User 99 not found"):
        await service.deactivate_user(user_id=99)


@pytest.mark.parametrize(
    ("remark", "expected_fragment"),
    [
        ("alice", "alice"),
        ("bob test", "bob%20test"),
    ],
)
def test_build_vless_url_contains_expected_parts(service: UserService, remark: str, expected_fragment: str):
    url = service._build_vless_url(
        user_uuid="uuid-1",
        exit_node_ip="1.2.3.4",
        x25519_public="pubkey",
        short_id="abc",
        reality_sni="www.microsoft.com",
        remark=remark,
    )

    assert "vless://uuid-1@1.2.3.4:443" in url
    assert expected_fragment in url
    assert "security=reality" in url


def test_generate_qr_code_returns_png_bytes(service: UserService):
    result = service._generate_qr_code("vless://test@1.2.3.4:443?security=reality")

    assert result[:4] == b"\x89PNG"
