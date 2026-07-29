"""Dynamic SNI rotation service with TLS health checks.

This service manages:
- SNI pool encryption/decryption (Fernet)
- TLS handshake health checks on port 443
- Time-based and failure-based SNI rotation
- Hot config reload without Xray restart
"""

import json
import logging
import ssl
import socket
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.database.models import Node, SSHKey
from bot.services.keygen import decrypt, encrypt
from bot.services.ssh import SSHClient
from bot.services.xray_api import XrayApiClient
from bot.templates import render_bridge_node_config, render_exit_node_config

logger = logging.getLogger(__name__)

# Default SNI pool with diverse, high-reputation domains
# Criteria: TLS 1.3 + H2 support, global CDN, low block probability
DEFAULT_SNI_POOL = [
    # Google (excellent TLS, rarely blocked)
    "dl.google.com",
    "www.google.com",
    "encrypted.google.com",
    # Microsoft (enterprise-grade)
    "www.microsoft.com",
    "update.microsoft.com",
    "download.microsoft.com",
    # Apple (global CDN)
    "cdn.apple.com",
    "www.apple.com",
    "updates.cdn-apple.com",
    # Amazon (multi-region)
    "www.amazon.com",
    "amazon.com",
    # Cloudflare (CDN + security)
    "www.cloudflare.com",
    "one.cloudflare.com",
    "cdn.cloudflare.com",
    # Other high-reputation CDNs
    "cdn.jsdelivr.net",
    "www.fastly.com",
    "cdn.mozilla.net",
    "www.shopify.com",
    "cdn.shopify.com",
    "www.github.com",
    "github.com",
]


class SNIRotationService:
    """Manages dynamic SNI rotation for proxy nodes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._http_client = httpx.AsyncClient(
            timeout=10.0,
            verify=settings.HTTPX_VERIFY,
        )

    async def close(self) -> None:
        """Close HTTP client."""
        await self._http_client.aclose()

    def _get_sni_pool(self, node: Node) -> list[str]:
        """Decrypt and return SNI pool for a node."""
        if not node.sni_pool_encrypted:
            return DEFAULT_SNI_POOL.copy()
        try:
            decrypted = decrypt(node.sni_pool_encrypted)
            pool = json.loads(decrypted)
            if isinstance(pool, list) and all(isinstance(s, str) for s in pool):
                return pool
        except Exception as e:
            logger.warning("Failed to decrypt SNI pool for node %d: %s", node.id, e)
        return DEFAULT_SNI_POOL.copy()

    def _save_sni_pool(self, node: Node, pool: list[str]) -> None:
        """Encrypt and save SNI pool for a node."""
        node.sni_pool_encrypted = encrypt(json.dumps(pool))

    def _get_current_sni(self, node: Node) -> str:
        """Get current active SNI for a node.

        Priority:
        1. Custom domain (reality_domain) for bridge nodes
        2. SNI from pool (by current_sni_index)
        3. Static reality_sni
        4. Default from settings
        """
        # Custom domain takes precedence
        if node.reality_domain:
            return node.reality_domain

        # Dynamic SNI pool
        if node.sni_pool_encrypted:
            pool = self._get_sni_pool(node)
            if pool and node.current_sni_index is not None:
                idx = node.current_sni_index % len(pool)
                return pool[idx]

        # Static SNI
        if node.reality_sni:
            return node.reality_sni

        # Global default
        return settings.REALITY_SNI

    async def check_tls_health(self, domain: str, port: int = 443) -> dict[str, Any]:
        """Perform TLS handshake health check.

        Returns dict with:
        - healthy: bool
        - tls_version: str (e.g., "TLSv1.3")
        - cipher: str
        - error: str | None
        - response_time_ms: float
        """
        result: dict[str, Any] = {
            "healthy": False,
            "tls_version": None,
            "cipher": None,
            "error": None,
            "response_time_ms": None,
        }

        try:
            start = datetime.now()
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.minimum_version = ssl.TLSVersion.TLSv1_2

            with socket.create_connection((domain, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    result["tls_version"] = ssock.version()
                    result["cipher"] = ssock.cipher()[0] if ssock.cipher() else None
                    elapsed = (datetime.now() - start).total_seconds() * 1000
                    result["response_time_ms"] = round(elapsed, 2)
                    result["healthy"] = True
                    logger.debug(
                        "TLS health OK for %s:%d (%s, %s, %.2fms)",
                        domain, port, result["tls_version"], result["cipher"], elapsed
                    )
        except ssl.SSLCertVerificationError as e:
            result["error"] = f"CERT_ERROR: {str(e)}"
            logger.warning("TLS cert error for %s:%d: %s", domain, port, e)
        except socket.timeout:
            result["error"] = "TIMEOUT"
            logger.warning("TLS health timeout for %s:%d", domain, port)
        except socket.gaierror as e:
            result["error"] = f"DNS_ERROR: {e}"
            logger.warning("DNS resolution failed for %s:%d: %s", domain, port, e)
        except Exception as e:
            result["error"] = f"ERROR: {type(e).__name__}: {e}"
            logger.exception("TLS health check failed for %s:%d", domain, port)

        return result

    async def rotate_sni(self, node_id: int, force: bool = False) -> dict[str, Any]:
        """Rotate SNI for a node.

        Args:
            node_id: Node ID to rotate
            force: If True, rotate regardless of interval

        Returns:
            Dict with rotation result details
        """
        async with self._session_factory() as session:
            node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
            if not node:
                return {"success": False, "error": f"Node {node_id} not found"}

            if node.reality_domain:
                return {
                    "success": False,
                    "error": "Node uses custom domain (reality_domain) - rotation not applicable"
                }

            pool = self._get_sni_pool(node)
            if len(pool) <= 1:
                return {"success": False, "error": "SNI pool has 0-1 domains, nothing to rotate"}

            # Check if rotation is needed
            now = datetime.utcnow()
            interval_h = node.sni_rotation_interval_h or 24
            last_rotation = node.last_sni_rotation_at

            if not force and last_rotation:
                next_rotation = last_rotation + timedelta(hours=interval_h)
                if now < next_rotation:
                    remaining = (next_rotation - now).total_seconds() / 60
                    return {
                        "success": False,
                        "skipped": True,
                        "message": f"Rotation not due yet ({remaining:.0f} minutes remaining)"
                    }

            # Check health of ALL SNI candidates (including current)
            current_sni = self._get_current_sni(node)
            old_index = node.current_sni_index if node.current_sni_index is not None else 0
            health_checks = []
            
            # Check all candidates starting from next, then wrap to current
            # This ensures we find the healthiest SNI, not just "next in line"
            checked_indices = []
            for i in range(len(pool)):
                idx = (old_index + i + 1) % len(pool)
                checked_indices.append(idx)
            
            # Also check current SNI last (to compare)
            checked_indices.append(old_index)
            
            new_index = old_index
            new_sni = current_sni
            
            for candidate_idx in checked_indices:
                candidate_sni = pool[candidate_idx]
                health = await self.check_tls_health(candidate_sni)
                health_checks.append({"domain": candidate_sni, **health})

                if health["healthy"] and candidate_idx != old_index:
                    # Found healthy alternative different from current
                    new_index = candidate_idx
                    new_sni = candidate_sni
                    break
            else:
                # No better alternative found - check if current is still healthy
                if not any(h["domain"] == current_sni and h["healthy"] for h in health_checks):
                    # Current SNI is unhealthy but no alternatives - fail
                    return {
                        "success": False,
                        "error": "All SNI candidates failed health check (including current)",
                        "health_checks": health_checks
                    }
                # Current is still OK - no rotation needed
                return {
                    "success": True,
                    "skipped": True,
                    "message": "Current SNI is healthy, no rotation needed",
                    "health_checks": health_checks
                }

            # Update node in DB
            node.current_sni_index = new_index
            node.last_sni_rotation_at = now
            node.reality_sni = new_sni  # ← Важно: обновляем reality_sni для подписки!
            await session.commit()

            # Hot reload Xray config
            try:
                await self._reload_node_config(session, node)
                reload_success = True
            except Exception as e:
                logger.exception("Failed to reload config after SNI rotation")
                reload_success = False
                # Rollback DB changes
                node.current_sni_index = old_index
                node.last_sni_rotation_at = last_rotation
                node.reality_sni = current_sni
                await session.commit()

            return {
                "success": reload_success,
                "old_sni": current_sni,
                "old_index": old_index,
                "new_sni": new_sni,
                "new_index": new_index,
                "health_checks": health_checks,
                "config_reloaded": reload_success
            }

    def _make_ssh_client(self, node: Node, ssh_key: SSHKey) -> SSHClient:
        """Create SSH client for node."""
        return SSHClient(node.ip or "", node.ssh_port, ssh_key.private_key_encrypted)

    def _make_xray_client(self, node: Node, ssh_key: SSHKey) -> XrayApiClient:
        """Create Xray API client for node."""
        ssh = self._make_ssh_client(node, ssh_key)
        return XrayApiClient(node.ip or "", node.xray_api_port, ssh)

    async def _reload_node_config(self, session: AsyncSession, node: Node) -> None:
        """Reload Xray config with new SNI (hot reload, no restart)."""
        key_result = await session.execute(select(SSHKey).where(SSHKey.id == node.ssh_key_id))
        ssh_key = key_result.scalar_one()

        ssh = self._make_ssh_client(node, ssh_key)
        xray = self._make_xray_client(node, ssh_key)

        if node.role == "exit":
            # Get users for this exit node
            from sqlalchemy import select as sql_select
            from bot.database.models import User, UserNode

            user_result = await session.execute(
                sql_select(User)
                .join(UserNode, UserNode.user_id == User.id)
                .where(UserNode.exit_node_id == node.id, User.is_active.is_(True))
            )
            users = list(user_result.scalars().all())
            client_uuids = [u.uuid for u in users]

            # Also include bridge UUIDs linked to this exit
            from bot.database.models import NodeLink
            bridge_result = await session.execute(
                sql_select(Node.bridge_uuid)
                .join(NodeLink, NodeLink.bridge_id == Node.id)
                .where(NodeLink.exit_id == node.id, Node.bridge_uuid.isnot(None))
            )
            client_uuids += [bu for (bu,) in bridge_result.all() if bu]

            x25519_priv = decrypt(node.x25519_private_encrypted)
            short_ids = (node.short_id or "").split(",") if node.short_id else []

            config_json = render_exit_node_config(
                clients=[{"uuid": u} for u in client_uuids],
                x25519_private=x25519_priv,
                short_ids=short_ids,
                reality_sni=self._get_current_sni(node),
                xray_api_port=node.xray_api_port,
                xhttp_host=settings.XHTTP_HOST,
                warp_enabled=node.warp_enabled,
                warp_secret_key=decrypt(node.warp_secret_key_encrypted) if node.warp_enabled and node.warp_secret_key_encrypted else "",
                warp_address=(node.warp_address or "").split(",") if node.warp_address else [],
                warp_reserved=node.warp_reserved or "0,0,0",
            )
        else:
            # Bridge node
            from bot.database.models import NodeLink
            link_result = await session.execute(
                sql_select(NodeLink).where(NodeLink.bridge_id == node.id)
            )
            link = link_result.scalar_one_or_none()
            if not link:
                raise ValueError(f"Bridge node {node.id} has no linked Exit node")

            exit_node = (await session.execute(
                sql_select(Node).where(Node.id == link.exit_id)
            )).scalar_one()

            if not node.bridge_uuid or not node.x25519_private_encrypted:
                raise ValueError(f"Bridge node {node.id} missing bridge_uuid/x25519")

            # Get users from exit node
            from bot.database.models import User, UserNode
            user_result = await session.execute(
                sql_select(User)
                .join(UserNode, UserNode.user_id == User.id)
                .where(UserNode.exit_node_id == exit_node.id, User.is_active.is_(True))
            )
            users = list(user_result.scalars().all())

            bx_priv = decrypt(node.x25519_private_encrypted)
            bridge_short_ids = (node.short_id or "").split(",") if node.short_id else []
            first_exit_sid = (exit_node.short_id or "").split(",")[0] if exit_node.short_id else ""

            config_json = render_bridge_node_config(
                clients=[{"uuid": u.uuid} for u in users],
                exit_node_ip=exit_node.ip or "",
                bridge_uuid=node.bridge_uuid,
                x25519_public=exit_node.x25519_public or "",
                short_id=first_exit_sid,
                reality_sni=self._get_current_sni(exit_node),
                bridge_x25519_private=bx_priv,
                bridge_short_ids=bridge_short_ids,
                bridge_reality_sni=self._get_current_sni(node),
                xhttp_host=settings.XHTTP_HOST,
                bridge_xhttp_host=settings.XHTTP_HOST,
                bridge_reality_domain=node.reality_domain,
                bridge_reality_dest="127.0.0.1:8443" if node.reality_domain else None,
                fingerprint=settings.FINGERPRINT,
            )

        # Deploy config via SSH
        logger.info(
            "SNI rotation: deploying config to node %d (role=%s, new_sni=%s)",
            node.id, node.role, self._get_current_sni(node)
        )
        await ssh.deploy_xray_config(config_json, xray_runtime=settings.XRAY_RUNTIME)
        logger.info(
            "SNI rotation: ✅ config deployed and Xray restarted on node %d (now serving SNI: %s)",
            node.id, self._get_current_sni(node)
        )

    async def set_sni_pool(self, node_id: int, pool: list[str]) -> dict[str, Any]:
        """Set custom SNI pool for a node.

        Args:
            node_id: Node ID
            pool: List of SNI domains

        Returns:
            Dict with operation result
        """
        if not pool:
            return {"success": False, "error": "SNI pool cannot be empty"}

        # Validate domains (basic check)
        for domain in pool:
            if not domain or " " in domain:
                return {"success": False, "error": f"Invalid domain in pool: {domain}"}

        async with self._session_factory() as session:
            node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
            if not node:
                return {"success": False, "error": f"Node {node_id} not found"}

            self._save_sni_pool(node, pool)
            node.current_sni_index = 0
            node.last_sni_rotation_at = datetime.utcnow()
            node.reality_sni = pool[0]  # ← Обновляем reality_sni первым доменом из пула
            await session.commit()

        # Reload config
        try:
            async with self._session_factory() as session:
                node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one()
                await self._reload_node_config(session, node)
            return {
                "success": True,
                "pool": pool,
                "current_sni": pool[0],
                "message": f"SNI pool set ({len(pool)} domains), config reloaded"
            }
        except Exception as e:
            logger.exception("Failed to reload config after setting SNI pool")
            return {"success": False, "error": f"Pool saved but config reload failed: {e}"}

    async def set_rotation_interval(self, node_id: int, interval_hours: int) -> dict[str, Any]:
        """Set SNI rotation interval for a node.

        Args:
            node_id: Node ID
            interval_hours: Rotation interval in hours (1-168)

        Returns:
            Dict with operation result
        """
        if not 1 <= interval_hours <= 168:
            return {"success": False, "error": "Interval must be 1-168 hours"}

        async with self._session_factory() as session:
            node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
            if not node:
                return {"success": False, "error": f"Node {node_id} not found"}

            node.sni_rotation_interval_h = interval_hours
            await session.commit()

        return {
            "success": True,
            "interval_hours": interval_hours,
            "message": f"Rotation interval set to {interval_hours}h"
        }

    async def check_all_nodes_health(self) -> list[dict[str, Any]]:
        """Check TLS health for all nodes' current SNI.

        Returns:
            List of health check results
        """
        async with self._session_factory() as session:
            nodes = (await session.execute(select(Node).where(Node.status == "active"))).scalars().all()

        results = []
        for node in nodes:
            sni = self._get_current_sni(node)
            health = await self.check_tls_health(sni)
            results.append({
                "node_id": node.id,
                "node_name": node.name,
                "role": node.role,
                "current_sni": sni,
                **health
            })
        return results
