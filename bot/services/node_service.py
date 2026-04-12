import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.database.models import Node, NodeLink, SSHKey, User
from bot.services.cloud.bitlaunch import BitLaunchClient
from bot.services.cloud.yandex import YandexClient
from bot.services.keygen import (
    decrypt,
    encrypt,
    generate_short_ids,
    generate_ssh_keypair,
    generate_uuid,
    generate_x25519_keypair,
)
from bot.services.ssh import SSHClient
from bot.templates import render_bridge_node_config, render_exit_node_config

logger = logging.getLogger(__name__)

_CLOUD_INIT_PATH = Path("scripts/cloud_init.sh")


class NodeService:
    def __init__(
        self,
        bitlaunch: BitLaunchClient,
        yandex: YandexClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._bitlaunch = bitlaunch
        self._yandex = yandex
        self._session_factory = session_factory

    async def _get_or_create_ssh_key(self, session: AsyncSession) -> SSHKey:
        result = await session.execute(select(SSHKey).limit(1))
        key = result.scalar_one_or_none()
        if key:
            return key
        private_pem, public_openssh = generate_ssh_keypair()
        key = SSHKey(
            name="bot-key",
            public_key=public_openssh,
            private_key_encrypted=encrypt(private_pem),
        )
        session.add(key)
        await session.commit()
        await session.refresh(key)
        return key

    def _make_ssh_client(self, node: Node, ssh_key: SSHKey) -> SSHClient:
        return SSHClient(node.ip or "", node.ssh_port, ssh_key.private_key_encrypted)

    async def _get_node_users(self, node: Node) -> list[User]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.exit_node_id == node.id, User.is_active == True)
            )
            return list(result.scalars().all())

    async def list_nodes(self) -> list[Node]:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).order_by(Node.created_at.desc()))
            return list(result.scalars().all())

    async def get_node(self, node_id: int) -> Node | None:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            return result.scalar_one_or_none()

    async def import_node(self, provider: str, provider_id: str, name: str, ip: str | None, role: str) -> Node:
        async with self._session_factory() as session:
            ssh_key = await self._get_or_create_ssh_key(session)
            node = Node(
                role=role,
                provider=provider,
                provider_id=provider_id,
                name=name,
                ip=ip,
                ssh_key_id=ssh_key.id,
                status="active",
            )
            session.add(node)
            await session.commit()
            await session.refresh(node)
            return node

    async def get_xray_status(self, node_id: int) -> str:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                raise ValueError(f"Node {node_id} not found")
            if not node.ip:
                raise ValueError(f"Node {node_id} has no IP address")
            key_result = await session.execute(select(SSHKey).where(SSHKey.id == node.ssh_key_id))
            ssh_key = key_result.scalar_one()

        ssh = self._make_ssh_client(node, ssh_key)
        return await ssh.xray_status()

    async def deploy_custom_config(self, node_id: int, config_json: str) -> None:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                raise ValueError(f"Node {node_id} not found")
            if not node.ip:
                raise ValueError(f"Node {node_id} has no IP address")
            key_result = await session.execute(select(SSHKey).where(SSHKey.id == node.ssh_key_id))
            ssh_key = key_result.scalar_one()

        ssh = self._make_ssh_client(node, ssh_key)
        await ssh.deploy_xray_config(config_json, xray_runtime=settings.XRAY_RUNTIME)
        logger.info("Custom config deployed to node %d", node_id)

    async def get_bot_public_key(self) -> str:
        async with self._session_factory() as session:
            result = await session.execute(select(SSHKey).limit(1))
            key = result.scalar_one_or_none()
        if not key:
            raise ValueError("No SSH key found. Start the bot first to generate one.")
        return key.public_key

    async def setup_node(self, node_id: int) -> Node:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                raise ValueError(f"Node {node_id} not found")
            if not node.ip:
                raise ValueError(f"Node {node_id} has no IP address")
            key_result = await session.execute(select(SSHKey).where(SSHKey.id == node.ssh_key_id))
            ssh_key = key_result.scalar_one()

        ssh = self._make_ssh_client(node, ssh_key)
        await ssh.setup_xray(api_port=node.xray_api_port)
        logger.info("Node %d xray installed", node_id)

        if node.role == "exit":
            x25519_priv, x25519_pub = await ssh.generate_x25519()
            node = await self.set_node_x25519(
                node_id=node_id,
                x25519_private=x25519_priv,
                x25519_public=x25519_pub,
            )
            logger.info("Node %d x25519 keys generated and saved", node_id)

        return node

    async def set_node_x25519(
        self,
        node_id: int,
        x25519_private: str,
        x25519_public: str,
        short_ids: list[str] | None = None,
        reality_sni: str | None = None,
    ) -> Node:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                raise ValueError(f"Node {node_id} not found")
            node.x25519_private_encrypted = encrypt(x25519_private)
            node.x25519_public = x25519_public
            if short_ids:
                node.short_id = ",".join(short_ids)
            elif not node.short_id:
                node.short_id = ",".join(generate_short_ids())
            if reality_sni:
                node.reality_sni = reality_sni
            await session.commit()
            await session.refresh(node)
            return node

    async def link_nodes(self, bridge_id: int, exit_id: int) -> NodeLink:
        async with self._session_factory() as session:
            link = NodeLink(bridge_id=bridge_id, exit_id=exit_id)
            session.add(link)
            await session.commit()
            return link

    async def redeploy_node(self, node_id: int) -> None:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                raise ValueError(f"Node {node_id} not found")
            key_result = await session.execute(select(SSHKey).where(SSHKey.id == node.ssh_key_id))
            ssh_key = key_result.scalar_one()

        ssh = self._make_ssh_client(node, ssh_key)

        if node.role == "exit":
            if not node.x25519_private_encrypted:
                raise ValueError(
                    f"Exit node {node_id} has no X25519 private key. "
                    "Use 'Set X25519 key' to add it after importing."
                )
            users = await self._get_node_users(node)
            x25519_priv = decrypt(node.x25519_private_encrypted)
            short_ids = (node.short_id or "").split(",") if node.short_id else generate_short_ids()
            config_json = render_exit_node_config(
                clients=[{"uuid": u.uuid} for u in users],
                x25519_private=x25519_priv,
                short_ids=short_ids,
                reality_sni=node.reality_sni or settings.REALITY_SNI,
                xray_api_port=node.xray_api_port,
                xhttp_host=settings.XHTTP_HOST,
            )
        else:
            async with self._session_factory() as session:
                link_result = await session.execute(
                    select(NodeLink).where(NodeLink.bridge_id == node_id)
                )
                link = link_result.scalar_one_or_none()
                if not link:
                    raise ValueError(f"Bridge node {node_id} has no linked Exit node")
                exit_result = await session.execute(select(Node).where(Node.id == link.exit_id))
                exit_node = exit_result.scalar_one()

            users = await self._get_node_users(exit_node)
            config_json = render_bridge_node_config(
                clients=[{"uuid": u.uuid} for u in users],
                exit_node_ip=exit_node.ip or "",
                bridge_uuid=generate_uuid(),
                x25519_public=exit_node.x25519_public or "",
                short_id=(exit_node.short_id or "").split(",")[0] if exit_node.short_id else "",
                reality_sni=exit_node.reality_sni or settings.REALITY_SNI,
            )

        await ssh.deploy_xray_config(config_json, xray_runtime=settings.XRAY_RUNTIME)
        logger.info("Node %d redeployed", node_id)

    async def redeploy_all_nodes(self) -> list[tuple[int, str, Exception | None]]:
        nodes = await self.list_nodes()
        active = [n for n in nodes if n.status == "active" and n.ip]
        results: list[tuple[int, str, Exception | None]] = []
        for node in active:
            try:
                await self.redeploy_node(node.id)
                results.append((node.id, node.name, None))
            except Exception as e:
                logger.exception("Failed to redeploy node %d", node.id)
                results.append((node.id, node.name, e))
        return results

    async def create_exit_node(
        self,
        name: str,
        image_id: str,
        size_id: str,
        region_id: str,
        reality_sni: str | None = None,
    ) -> Node:
        sni = reality_sni or settings.REALITY_SNI
        init_script = _CLOUD_INIT_PATH.read_text()

        async with self._session_factory() as session:
            ssh_key = await self._get_or_create_ssh_key(session)

        bl_key = await self._bitlaunch.create_ssh_key(f"bot-{datetime.utcnow().date()}", ssh_key.public_key)
        bl_key_id = str(bl_key["id"])

        server = await self._bitlaunch.create_server(
            name=name,
            image_id=image_id,
            size_id=size_id,
            region_id=region_id,
            ssh_key_ids=[bl_key_id],
            init_script=init_script,
        )
        server_id = str(server["id"])
        ip = await self._bitlaunch.wait_for_ip(server_id)

        x25519_priv, x25519_pub = generate_x25519_keypair()
        short_ids = generate_short_ids()
        short_ids_str = ",".join(short_ids)

        async with self._session_factory() as session:
            ssh_key = await self._get_or_create_ssh_key(session)
            node = Node(
                role="exit",
                provider="bitlaunch",
                provider_id=server_id,
                name=name,
                ip=ip,
                ssh_key_id=ssh_key.id,
                x25519_private_encrypted=encrypt(x25519_priv),
                x25519_public=x25519_pub,
                short_id=short_ids_str,
                reality_sni=sni,
                xray_api_port=settings.XRAY_API_PORT,
                status="provisioning",
            )
            session.add(node)
            await session.commit()
            await session.refresh(node)

        ssh = self._make_ssh_client(node, ssh_key)
        config_json = render_exit_node_config(
            clients=[],
            x25519_private=x25519_priv,
            short_ids=short_ids,
            reality_sni=sni,
            xray_api_port=settings.XRAY_API_PORT,
            xhttp_host=settings.XHTTP_HOST,
        )
        await ssh.deploy_xray_config(config_json, xray_runtime=settings.XRAY_RUNTIME)

        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node.id))
            node = result.scalar_one()
            node.status = "active"
            await session.commit()
            await session.refresh(node)

        return node

    async def create_bridge_node(
        self,
        name: str,
        exit_node_id: int,
        zone_id: str | None = None,
        subnet_id: str | None = None,
    ) -> Node:
        init_script = _CLOUD_INIT_PATH.read_text()

        async with self._session_factory() as session:
            ssh_key = await self._get_or_create_ssh_key(session)
            result = await session.execute(select(Node).where(Node.id == exit_node_id))
            exit_node = result.scalar_one_or_none()

        if not exit_node or exit_node.role != "exit":
            raise ValueError(f"Exit node {exit_node_id} not found")

        operation = await self._yandex.create_instance(
            name=name,
            zone_id=zone_id,
            subnet_id=subnet_id,
            ssh_public_key=ssh_key.public_key,
            init_script=init_script,
        )
        op = await self._yandex.wait_for_operation(operation["id"])
        instance_id = op.get("response", {}).get("id") or op.get("metadata", {}).get("instanceId", "")
        ip = await self._yandex.wait_for_instance_ip(instance_id)
        bridge_uuid = generate_uuid()

        async with self._session_factory() as session:
            ssh_key = await self._get_or_create_ssh_key(session)
            node = Node(
                role="bridge",
                provider="yandex",
                provider_id=instance_id,
                name=name,
                ip=ip,
                ssh_key_id=ssh_key.id,
                reality_sni=exit_node.reality_sni,
                xray_api_port=settings.XRAY_API_PORT,
                status="provisioning",
            )
            session.add(node)
            await session.flush()
            link = NodeLink(bridge_id=node.id, exit_id=exit_node.id)
            session.add(link)
            await session.commit()
            await session.refresh(node)

        ssh = self._make_ssh_client(node, ssh_key)
        first_short_id = (exit_node.short_id or "").split(",")[0] if exit_node.short_id else ""
        config_json = render_bridge_node_config(
            clients=[],
            exit_node_ip=exit_node.ip or "",
            bridge_uuid=bridge_uuid,
            x25519_public=exit_node.x25519_public or "",
            short_id=first_short_id,
            reality_sni=exit_node.reality_sni or settings.REALITY_SNI,
        )
        await ssh.deploy_xray_config(config_json, xray_runtime=settings.XRAY_RUNTIME)

        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node.id))
            node = result.scalar_one()
            node.status = "active"
            await session.commit()
            await session.refresh(node)

        return node

    async def delete_node(self, node_id: int) -> None:
        async with self._session_factory() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                raise ValueError(f"Node {node_id} not found")
            node.status = "deleting"
            await session.commit()

        if node.provider == "bitlaunch":
            await self._bitlaunch.delete_server(node.provider_id)
        elif node.provider == "yandex":
            await self._yandex.delete_instance(node.provider_id)

        async with self._session_factory() as session:
            await session.execute(
                sql_delete(NodeLink).where(
                    (NodeLink.bridge_id == node_id) | (NodeLink.exit_id == node_id)
                )
            )
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one()
            await session.delete(node)
            await session.commit()

    async def recreate_bridge_node(self, bridge_node_id: int) -> Node:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Node, NodeLink)
                .join(NodeLink, NodeLink.bridge_id == Node.id)
                .where(Node.id == bridge_node_id)
            )
            row = result.first()

        if not row:
            raise ValueError(f"Bridge node {bridge_node_id} not found or has no Exit link")

        old_node, link = row
        exit_node_id = link.exit_id
        name = f"{old_node.name}-new"

        await self.delete_node(bridge_node_id)
        return await self.create_bridge_node(name, exit_node_id)
