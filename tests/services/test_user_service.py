from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.database.models import Node, SSHKey, User
from bot.services.user_service import UserService


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
def mock_node_service(mocker):
    from bot.services.node_service import NodeService
    svc = mocker.Mock(spec=NodeService)
    svc.redeploy_node = mocker.AsyncMock()
    svc.redeploy_exit_with_bridges = mocker.AsyncMock()
    return svc


@pytest.fixture()
def service(session_factory, mocker, mock_node_service) -> UserService:
    svc = UserService(session_factory=session_factory, node_service=mock_node_service)
    return svc


def _make_scalar_result(mocker, value):
    result = mocker.Mock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def _make_bridge_result(mocker, value):
    """Результат для select(...).scalars().first() — поиск bridge."""
    result = mocker.Mock()
    scalars = mocker.Mock()
    scalars.first.return_value = value
    result.scalars.return_value = scalars
    return result


def _make_all_result(mocker, rows):
    """Результат для execute(...).all() — поиск нескольких строк (bridge+ssh_key)."""
    result = mocker.Mock()
    result.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_create_user_saves_user_and_redeploys(
    service: UserService,
    session_factory,
    mock_session,
    exit_node: Node,
    ssh_key: SSHKey,
    active_user: User,
    mock_node_service,
    mocker,
):
    """Test create_user uses redeploy (not add_user API) for Xray v25+."""
    mock_session.execute.side_effect = [
        _make_scalar_result(mocker, exit_node),   # exit lookup (валидация первичного exit)
        _make_scalar_result(mocker, ssh_key),     # ssh_key lookup
    ]
    mock_session.add = mocker.Mock()
    mock_session.flush = mocker.AsyncMock()
    mock_session.commit = mocker.AsyncMock()
    mock_session.refresh = mocker.AsyncMock()
    session_factory.return_value = mock_session
    
    # M:N: хот-аддим через redeploy
    mocker.patch.object(service, "_get_node_with_key", mocker.AsyncMock(return_value=(exit_node, ssh_key)))
    mocker.patch.object(service, "get_user_bridge_config", mocker.AsyncMock(side_effect=ValueError("no bridge")))

    user, vless_url, qr_bytes, bridge_url, bridge_qr = await service.create_user(
        name="alice", exit_node_id=10
    )

    # Xray v25+: используем redeploy вместо add_user API
    mock_node_service.redeploy_exit_with_bridges.assert_called_once_with(10)
    assert "1.2.3.4" in vless_url
    assert len(qr_bytes) > 0
    # subscription_token сгенерён при создании
    assert user.subscription_token
    # bridge не привязан → bridge-ссылки нет
    assert bridge_url is None
    assert bridge_qr is None


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
    mock_node_service,
    mocker,
):
    """Test deactivate_user uses redeploy (not remove_user API) for Xray v25+."""
    # get_user_nodes вызывается в отдельном async with — мокаем его напрямую
    mocker.patch.object(service, "get_user_nodes", mocker.AsyncMock(return_value=[exit_node]))

    mock_session.execute.side_effect = [
        _make_scalar_result(mocker, active_user),  # deactivate: user lookup
        _make_scalar_result(mocker, active_user),   # deactivate: final user update
    ]
    mock_session.commit = mocker.AsyncMock()
    mock_session.delete = mocker.AsyncMock()
    session_factory.return_value = mock_session
    mock_session.__aenter__.return_value = mock_session

    await service.deactivate_user(user_id=1, delete_from_db=False)

    # Xray v25+: используем redeploy вместо remove_user API
    mock_node_service.redeploy_exit_with_bridges.assert_called_once_with(10)
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
    mock_node_service,
    mocker,
):
    """Test deactivate_user with delete_from_db=True uses redeploy and deletes from DB."""
    # get_user_nodes вызывается в отдельном async with — мокаем его напрямую
    mocker.patch.object(service, "get_user_nodes", mocker.AsyncMock(return_value=[exit_node]))

    # UserNode rows for deletion
    user_node = mocker.Mock()
    un_scalars_mock = mocker.Mock()
    un_scalars_mock.all.return_value = [user_node]
    user_nodes_result = mocker.Mock()
    user_nodes_result.scalars.return_value = un_scalars_mock

    mock_session.execute.side_effect = [
        _make_scalar_result(mocker, active_user),  # deactivate: user lookup
        _make_scalar_result(mocker, active_user),   # deactivate: user for delete
        user_nodes_result,                          # delete: UserNode rows (scalars().all())
    ]
    mock_session.commit = mocker.AsyncMock()
    mock_session.delete = mocker.AsyncMock()
    session_factory.return_value = mock_session
    mock_session.__aenter__.return_value = mock_session

    await service.deactivate_user(user_id=1, delete_from_db=True)

    # Xray v25+: используем redeploy вместо remove_user API
    mock_node_service.redeploy_exit_with_bridges.assert_called_once_with(10)
    # delete вызывается дважды: сначала для UserNode, потом для User
    assert mock_session.delete.call_count == 2
    # Второй вызов — удаление пользователя
    assert mock_session.delete.call_args_list[1].args[0] == active_user


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
    # fingerprint из config (мок conftest = chrome) + spiderX для мимикрии handshake
    assert "fp=chrome" in url
    assert "spx=%2F" in url


def test_generate_qr_code_returns_png_bytes(service: UserService):
    result = service._generate_qr_code("vless://test@1.2.3.4:443?security=reality")

    assert result[:4] == b"\x89PNG"


def test_subscription_url_format(service: UserService):
    # SUB_URL_BASE мокнут в conftest = https://sub.example.com
    assert service._subscription_url("tok123") == "https://sub.example.com/sub/tok123"


@pytest.mark.asyncio
async def test_get_subscription_payload_unknown_token_returns_none(
    service: UserService, session_factory, mock_session, mocker
):
    mock_session.execute.return_value = _make_scalar_result(mocker, None)
    session_factory.return_value = mock_session

    assert await service.get_subscription_payload("nope") is None


@pytest.mark.asyncio
async def test_get_subscription_payload_inactive_user_returns_none(
    service: UserService, session_factory, mock_session, active_user: User, mocker
):
    active_user.is_active = False
    active_user.subscription_token = "tok"
    mock_session.execute.return_value = _make_scalar_result(mocker, active_user)
    session_factory.return_value = mock_session

    assert await service.get_subscription_payload("tok") is None


@pytest.mark.asyncio
async def test_get_subscription_payload_returns_base64_and_headers(
    service: UserService, session_factory, mock_session, active_user: User, mocker
):
    import base64

    active_user.is_active = True
    active_user.subscription_token = "tok"
    mock_session.execute.return_value = _make_scalar_result(mocker, active_user)
    session_factory.return_value = mock_session
    # сборку ссылок мокаем — проверяем обёртку payload
    mocker.patch.object(
        service,
        "build_user_links",
        mocker.AsyncMock(return_value=[("a", "vless://1"), ("b", "vless://2")]),
    )

    body_b64, headers = await service.get_subscription_payload("tok")

    decoded = base64.b64decode(body_b64).decode()
    assert decoded == "vless://1\nvless://2"
    assert "Profile-Title" in headers
    assert headers["Profile-Update-Interval"] == "12"
    assert "Subscription-Userinfo" in headers


@pytest.mark.asyncio
async def test_rotate_subscription_changes_token(
    service: UserService, session_factory, mock_session, active_user: User, mocker
):
    active_user.subscription_token = "old-token"
    mock_session.execute.return_value = _make_scalar_result(mocker, active_user)
    mock_session.commit = mocker.AsyncMock()
    mock_session.refresh = mocker.AsyncMock()
    session_factory.return_value = mock_session

    url = await service.rotate_subscription(active_user.id)

    assert active_user.subscription_token != "old-token"
    assert url.startswith("https://sub.example.com/sub/")
