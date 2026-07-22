import base64
import io
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

import qrcode
import qrcode.constants
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.database.models import Node, NodeLink, SSHKey, User, UserNode
from bot.services.keygen import generate_subscription_token, generate_uuid
from bot.services.ssh import SSHClient
from bot.services.xray_api import XrayApiClient

if TYPE_CHECKING:
    from bot.services.node_service import NodeService

logger = logging.getLogger(__name__)


class UserService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        node_service: "NodeService | None" = None,
    ) -> None:
        self._session_factory = session_factory
        self._node_service = node_service

    def _build_vless_url(
        self,
        user_uuid: str,
        exit_node_ip: str,
        x25519_public: str,
        short_id: str,
        reality_sni: str,
        remark: str,
        xhttp_host: str = "",
        xhttp_path: str = "/xhttptransmissionpath",
        port: int = 443,
    ) -> str:
        first_short_id = short_id.split(",")[0] if "," in short_id else short_id
        effective_host = xhttp_host or reality_sni
        params = "&".join([
            "encryption=none",
            "security=reality",
            f"sni={reality_sni}",
            f"fp={settings.FINGERPRINT}",
            f"pbk={x25519_public}",
            f"sid={first_short_id}",
            "spx=%2F",  # spiderX=/ — улучшает мимикрию REALITY-handshake
            "type=xhttp",
            f"path={quote(xhttp_path)}",
            f"host={effective_host}",
        ])
        return f"vless://{user_uuid}@{exit_node_ip}:{port}?{params}#{quote(remark)}"

    def _generate_qr_code(self, vless_url: str) -> bytes:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(vless_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _make_xray_client(self, node: Node, ssh_key: SSHKey) -> XrayApiClient:
        ssh = SSHClient(node.ip or "", node.ssh_port, ssh_key.private_key_encrypted)
        return XrayApiClient(node.ip or "", node.xray_api_port, ssh)

    async def _add_user_to_running_nodes(
        self, exit_node: Node, exit_ssh_key: SSHKey, user_uuid: str
    ) -> None:
        """Горячее добавление юзера в Exit и привязанные Bridge через Xray API.

        Xray v25+: API команды adduser/removeuser НЕ поддерживаются напрямую.
        Вместо этого делаем redeploy ноды (тест+рестарт+rollback при ошибке).
        """
        if not self._node_service:
            logger.warning("NodeService not available, cannot add user to nodes")
            return

        try:
            await self._node_service.redeploy_exit_with_bridges(exit_node.id)
            logger.info("User %s added to node %d via redeploy", user_uuid, exit_node.id)
        except Exception as e:
            logger.exception("Failed to redeploy node %d for user add", exit_node.id)
            raise

    async def _get_node_with_key(self, node_id: int) -> tuple[Node | None, SSHKey | None]:
        async with self._session_factory() as session:
            node = (
                await session.execute(select(Node).where(Node.id == node_id))
            ).scalar_one_or_none()
            if not node:
                return None, None
            key = (
                await session.execute(select(SSHKey).where(SSHKey.id == node.ssh_key_id))
            ).scalar_one_or_none()
            return node, key

    async def get_user_nodes(self, user_id: int) -> list[Node]:
        """Все exit-ноды юзера (из user_nodes). Лениво засеивает первичный exit, если
        таблица пуста для этого юзера (backfill для старых юзеров)."""
        async with self._session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")
            rows = await session.execute(
                select(Node)
                .join(UserNode, UserNode.exit_node_id == Node.id)
                .where(UserNode.user_id == user_id)
            )
            nodes = list(rows.scalars().all())
            if not nodes:
                # backfill: старый юзер без строк user_nodes — досоздать по exit_node_id
                session.add(UserNode(user_id=user_id, exit_node_id=user.exit_node_id))
                await session.commit()
                primary = (
                    await session.execute(select(Node).where(Node.id == user.exit_node_id))
                ).scalar_one_or_none()
                nodes = [primary] if primary else []
            return nodes

    async def build_user_links(self, user_id: int) -> list[tuple[str, str]]:
        """Все VLESS-ссылки юзера: по каждой его exit-ноде — прямая + bridge (если есть).

        Возвращает [(remark, vless_url), ...]. Переиспользует _build_vless_url.
        """
        nodes = await self.get_user_nodes(user_id)
        async with self._session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            links: list[tuple[str, str]] = []
            for exit_node in nodes:
                if exit_node.ip and exit_node.x25519_public:
                    remark = f"{user.name} · {exit_node.name}"
                    links.append((remark, self._build_vless_url(
                        user_uuid=user.uuid,
                        exit_node_ip=exit_node.ip,
                        x25519_public=exit_node.x25519_public,
                        short_id=exit_node.short_id or "",
                        reality_sni=exit_node.reality_sni or settings.REALITY_SNI,
                        remark=remark,
                        xhttp_host=settings.XHTTP_HOST,
                    )))
                # bridge(ы), привязанные к этой exit-ноде
                bridge_rows = await session.execute(
                    select(Node)
                    .join(NodeLink, NodeLink.bridge_id == Node.id)
                    .where(NodeLink.exit_id == exit_node.id, Node.role == "bridge")
                )
                for bridge in bridge_rows.scalars().all():
                    if not bridge.ip or not bridge.x25519_public:
                        continue
                    bremark = f"{user.name} · {bridge.name} (bridge)"
                    links.append((bremark, self._build_vless_url(
                        user_uuid=user.uuid,
                        exit_node_ip=bridge.ip,
                        x25519_public=bridge.x25519_public,
                        short_id=bridge.short_id or "",
                        reality_sni=bridge.reality_sni or settings.REALITY_SNI,
                        remark=bremark,
                        xhttp_host=settings.XHTTP_HOST,
                    )))
            return links

    async def get_subscription_payload(self, token: str) -> tuple[str, dict[str, str]] | None:
        """По subscription-токену собрать base64-подписку + заголовки Hiddify/Happ.

        Возвращает None, если токен неизвестен или юзер неактивен (→ 404).
        """
        if not token:
            return None
        async with self._session_factory() as session:
            user = (
                await session.execute(
                    select(User).where(User.subscription_token == token)
                )
            ).scalar_one_or_none()
            if not user or not user.is_active:
                return None
            user_id, user_name = user.id, user.name

        links = await self.build_user_links(user_id)
        body = "\n".join(url for _, url in links)
        body_b64 = base64.b64encode(body.encode()).decode()

        title_b64 = base64.b64encode(f"{user_name} proxy".encode()).decode()
        headers = {
            "Profile-Title": f"base64:{title_b64}",
            "Profile-Update-Interval": str(settings.SUB_UPDATE_INTERVAL_H),
            "Subscription-Userinfo": "upload=0; download=0; total=0; expire=0",
        }
        return body_b64, headers

    async def ensure_subscription(self, user_id: int) -> str:
        """Вернуть полный subscription-URL юзера (сгенерить токен, если нет)."""
        async with self._session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")
            if not user.subscription_token:
                user.subscription_token = generate_subscription_token()
                await session.commit()
                await session.refresh(user)
            token = user.subscription_token
        return self._subscription_url(token)

    async def rotate_subscription(self, user_id: int) -> str:
        """Перевыпустить токен (старый URL перестаёт работать)."""
        async with self._session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")
            user.subscription_token = generate_subscription_token()
            await session.commit()
            await session.refresh(user)
            token = user.subscription_token
        return self._subscription_url(token)

    @staticmethod
    def _subscription_url(token: str) -> str:
        base = settings.SUB_URL_BASE.rstrip("/")
        return f"{base}/sub/{token}"

    async def list_users(self, exit_node_id: int | None = None) -> list[User]:
        async with self._session_factory() as session:
            query = select(User)
            if exit_node_id is not None:
                query = query.where(User.exit_node_id == exit_node_id)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def create_user(
        self,
        name: str,
        exit_node_id: int,
        telegram_id: int | None = None,
        extra_exit_ids: list[int] | None = None,
    ) -> tuple[User, str, bytes, str | None, bytes | None]:
        # Полный набор exit для юзера: первичный + дополнительные (для подписки).
        all_exit_ids = [exit_node_id] + [
            e for e in (extra_exit_ids or []) if e != exit_node_id
        ]

        async with self._session_factory() as session:
            node_result = await session.execute(select(Node).where(Node.id == exit_node_id))
            exit_node = node_result.scalar_one_or_none()

            if not exit_node or exit_node.role != "exit":
                raise ValueError(f"Exit node {exit_node_id} not found")
            if not exit_node.ip:
                raise ValueError(f"Exit node {exit_node_id} has no IP yet")

            key_result = await session.execute(select(SSHKey).where(SSHKey.id == exit_node.ssh_key_id))
            ssh_key = key_result.scalar_one()

        user_uuid = generate_uuid()

        async with self._session_factory() as session:
            user = User(
                name=name,
                uuid=user_uuid,
                exit_node_id=exit_node_id,
                telegram_id=telegram_id,
                is_active=True,
                subscription_token=generate_subscription_token(),
            )
            session.add(user)
            await session.flush()
            for eid in all_exit_ids:
                session.add(UserNode(user_id=user.id, exit_node_id=eid))
            await session.commit()
            await session.refresh(user)

        # Горячее добавление без рестарта на КАЖДУЮ exit-ноду (+ её bridge).
        for eid in all_exit_ids:
            node, key = await self._get_node_with_key(eid)
            if node and key and node.ip:
                await self._add_user_to_running_nodes(node, key, user_uuid)

        vless_url = self._build_vless_url(
            user_uuid=user_uuid,
            exit_node_ip=exit_node.ip,
            x25519_public=exit_node.x25519_public or "",
            short_id=exit_node.short_id or "",
            reality_sni=exit_node.reality_sni or settings.REALITY_SNI,
            remark=name,
            xhttp_host=settings.XHTTP_HOST,
        )
        qr_bytes = self._generate_qr_code(vless_url)

        # Если к exit привязан bridge — отдаём и bridge-ссылку (RU IP, лучше против РКН).
        bridge_url: str | None = None
        bridge_qr: bytes | None = None
        try:
            bridge_url, bridge_qr = await self.get_user_bridge_config(user.id)
        except ValueError:
            pass  # bridge не привязан/не готов — отдаём только exit-ссылку

        return user, vless_url, qr_bytes, bridge_url, bridge_qr

    async def get_user_config(self, user_id: int) -> tuple[str, bytes]:
        async with self._session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")

            node_result = await session.execute(select(Node).where(Node.id == user.exit_node_id))
            exit_node = node_result.scalar_one()

        vless_url = self._build_vless_url(
            user_uuid=user.uuid,
            exit_node_ip=exit_node.ip or "",
            x25519_public=exit_node.x25519_public or "",
            short_id=exit_node.short_id or "",
            reality_sni=exit_node.reality_sni or settings.REALITY_SNI,
            remark=user.name,
            xhttp_host=settings.XHTTP_HOST,
        )
        qr_bytes = self._generate_qr_code(vless_url)
        return vless_url, qr_bytes

    async def get_user_bridge_config(self, user_id: int) -> tuple[str, bytes]:
        """Конфиг, маршрутизирующий клиента через Bridge (RU IP) → Exit.

        Ищет Bridge, привязанный к exit-ноде юзера, и строит ссылку на Bridge
        с REALITY-параметрами самого Bridge (плечо клиент↔bridge).
        """
        async with self._session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")

            bridge_result = await session.execute(
                select(Node)
                .join(NodeLink, NodeLink.bridge_id == Node.id)
                .where(NodeLink.exit_id == user.exit_node_id, Node.role == "bridge")
            )
            bridge = bridge_result.scalars().first()

        if not bridge:
            raise ValueError(
                f"No bridge linked to exit node #{user.exit_node_id} for user {user_id}"
            )
        if not bridge.ip or not bridge.x25519_public:
            raise ValueError(f"Bridge #{bridge.id} is not fully configured (no IP/x25519)")

        vless_url = self._build_vless_url(
            user_uuid=user.uuid,
            exit_node_ip=bridge.ip,
            x25519_public=bridge.x25519_public,
            short_id=bridge.short_id or "",
            reality_sni=bridge.reality_sni or settings.REALITY_SNI,
            remark=f"{user.name} (via bridge)",
            xhttp_host=settings.XHTTP_HOST,
        )
        qr_bytes = self._generate_qr_code(vless_url)
        return vless_url, qr_bytes

    async def add_node_to_subscription(self, user_id: int, node_id: int) -> dict:
        """Add an exit node to user's subscription (M:N).

        Returns dict with result status and details.
        """
        async with self._session_factory() as session:
            # Check user exists
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if not user:
                return {"success": False, "error": f"User {user_id} not found"}

            # Check node exists and is exit
            node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
            if not node:
                return {"success": False, "error": f"Node {node_id} not found"}
            if node.role != "exit":
                return {"success": False, "error": f"Node {node_id} is not an exit node"}

            # Check if already in subscription
            existing = (await session.execute(
                select(UserNode).where(UserNode.user_id == user_id, UserNode.exit_node_id == node_id)
            )).scalar_one_or_none()
            if existing:
                return {"success": False, "error": f"Node {node_id} already in subscription"}

            # Add to subscription
            session.add(UserNode(user_id=user_id, exit_node_id=node_id))
            await session.commit()

        # Hot-add user to the new node
        node_key = await self._get_node_with_key(node_id)
        if node_key[0] and node_key[1] and node.ip:
            try:
                await self._add_user_to_running_nodes(node_key[0], node_key[1], user.uuid)
            except Exception as e:
                logger.exception("Failed to hot-add user to node %d", node_id)
                return {"success": False, "error": f"Added to DB but hot-add failed: {e}"}

        return {"success": True, "node_name": node.name, "message": f"Node {node.name} added to subscription"}

    async def remove_node_from_subscription(self, user_id: int, node_id: int) -> dict:
        """Remove an exit node from user's subscription (M:N).

        Returns dict with result status and details.
        """
        async with self._session_factory() as session:
            # Check user exists
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if not user:
                return {"success": False, "error": f"User {user_id} not found"}

            # Check node exists
            node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
            if not node:
                return {"success": False, "error": f"Node {node_id} not found"}

            # Check if in subscription
            user_node = (await session.execute(
                select(UserNode).where(UserNode.user_id == user_id, UserNode.exit_node_id == node_id)
            )).scalar_one_or_none()
            if not user_node:
                return {"success": False, "error": f"Node {node_id} not in subscription"}

            # Can't remove primary exit node
            if user.exit_node_id == node_id:
                return {"success": False, "error": "Cannot remove primary exit node (change primary first)"}

            # Delete M:N record first
            await session.delete(user_node)
            await session.commit()

        # Redeploy node to update config (remove user from Xray)
        if self._node_service:
            try:
                await self._node_service.redeploy_exit_with_bridges(node_id)
                logger.info("Node %d redeployed after removing user %d", node_id, user_id)
            except Exception as e:
                logger.exception("Failed to redeploy node %d after removal", node_id)
                # Rollback: restore the M:N record
                async with self._session_factory() as session:
                    session.add(UserNode(user_id=user_id, exit_node_id=node_id))
                    await session.commit()
                return {"success": False, "error": f"Redeploy failed: {e}"}

        return {"success": True, "node_name": node.name, "message": f"Node {node.name} removed from subscription"}

    async def get_subscription_nodes(self, user_id: int) -> list[Node]:
        """Get all exit nodes in user's subscription."""
        return await self.get_user_nodes(user_id)

    async def set_primary_exit_node(self, user_id: int, node_id: int) -> dict:
        """Set primary exit node for user.

        This changes User.exit_node_id (the main node for this user).
        """
        async with self._session_factory() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if not user:
                return {"success": False, "error": f"User {user_id} not found"}

            node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
            if not node:
                return {"success": False, "error": f"Node {node_id} not found"}
            if node.role != "exit":
                return {"success": False, "error": f"Node {node_id} is not an exit node"}

            # Ensure node is in subscription
            existing = (await session.execute(
                select(UserNode).where(UserNode.user_id == user_id, UserNode.exit_node_id == node_id)
            )).scalar_one_or_none()
            if not existing:
                session.add(UserNode(user_id=user_id, exit_node_id=node_id))

            user.exit_node_id = node_id
            await session.commit()

        return {"success": True, "node_name": node.name, "message": f"Primary exit set to {node.name}"}

    async def deactivate_user(self, user_id: int, delete_from_db: bool = False) -> None:
        async with self._session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")
            user_uuid = user.uuid

        # Все exit-ноды юзера (M:N) — redeploy для удаления UUID из конфигов.
        exit_nodes = await self.get_user_nodes(user_id)
        exit_ids = [n.id for n in exit_nodes]

        # Redeploy all nodes to remove user from configs
        if self._node_service:
            for eid in exit_nodes:
                try:
                    await self._node_service.redeploy_exit_with_bridges(eid.id)
                    logger.info("User %s removed from node %d via redeploy", user_uuid, eid.id)
                except Exception as e:
                    logger.exception("redeploy failed on node %d for user deactivation", eid.id)

        async with self._session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
            if delete_from_db:
                # Сначала чистим M:N-строки (нет каскада во избежание FK-сирот).
                links = await session.execute(
                    select(UserNode).where(UserNode.user_id == user_id)
                )
                for ln in links.scalars().all():
                    await session.delete(ln)
                await session.delete(user)
            else:
                user.is_active = False
            await session.commit()
