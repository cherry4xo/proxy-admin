import io
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

import qrcode
import qrcode.constants
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.database.models import Node, NodeLink, SSHKey, User
from bot.services.keygen import generate_uuid
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
            "fp=chrome",
            f"pbk={x25519_public}",
            f"sid={first_short_id}",
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
        """Горячее добавление юзера в Exit и привязанные Bridge без рестарта.

        При любой ошибке откатываемся на полный безопасный redeploy
        (test+restart+rollback), который рендерит конфиг из БД — источника истины.
        """
        try:
            xray = self._make_xray_client(exit_node, exit_ssh_key)
            await xray.add_user("inbound-vless", user_uuid, flow="")

            async with self._session_factory() as session:
                bridge_rows = await session.execute(
                    select(Node, SSHKey)
                    .join(NodeLink, NodeLink.bridge_id == Node.id)
                    .join(SSHKey, SSHKey.id == Node.ssh_key_id)
                    .where(NodeLink.exit_id == exit_node.id, Node.role == "bridge")
                )
                bridges = list(bridge_rows.all())

            for bridge, bridge_key in bridges:
                if not bridge.ip:
                    continue
                bxray = self._make_xray_client(bridge, bridge_key)
                await bxray.add_user("inbound-client", user_uuid, flow="")
        except Exception:
            logger.exception("adduser fast-path failed, falling back to redeploy")
            if self._node_service:
                await self._node_service.redeploy_exit_with_bridges(exit_node.id)

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
    ) -> tuple[User, str, bytes, str | None, bytes | None]:
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
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        # Горячее добавление без рестарта (fallback на redeploy внутри хелпера).
        await self._add_user_to_running_nodes(exit_node, ssh_key, user_uuid)

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

    async def deactivate_user(self, user_id: int, delete_from_db: bool = False) -> None:
        async with self._session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")

            node_result = await session.execute(select(Node).where(Node.id == user.exit_node_id))
            exit_node = node_result.scalar_one()

            key_result = await session.execute(select(SSHKey).where(SSHKey.id == exit_node.ssh_key_id))
            ssh_key = key_result.scalar_one()

        xray = self._make_xray_client(exit_node, ssh_key)
        await xray.remove_user("inbound-vless", user.uuid)

        async with self._session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
            if delete_from_db:
                await session.delete(user)
            else:
                user.is_active = False
            await session.commit()

        if self._node_service:
            await self._node_service.redeploy_exit_with_bridges(exit_node.id)
