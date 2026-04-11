import asyncio
import logging
from typing import Any

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://app.bitlaunch.io/api"


class BitLaunchClient:
    def __init__(self, api_token: str, host_id: int, verify_ssl: bool = True) -> None:
        self._api_token = api_token
        self._host_id = host_id
        self._verify_ssl = verify_ssl

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {self._api_token}"},
            timeout=30.0,
            verify=self._verify_ssl,
        )

    async def list_servers(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get("/servers")
            r.raise_for_status()
            data = r.json()
            return data.get("servers", data) if isinstance(data, dict) else data

    async def get_server(self, server_id: str) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get(f"/servers/{server_id}")
            r.raise_for_status()
            return r.json()

    async def create_server(
        self,
        name: str,
        image_id: str,
        size_id: str,
        region_id: str,
        ssh_key_ids: list[str],
        init_script: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "hostID": self._host_id,
            "hostImageID": image_id,
            "sizeID": size_id,
            "regionID": region_id,
            "sshKeys": ssh_key_ids,
        }
        if init_script:
            payload["initscript"] = init_script
        async with self._client() as c:
            r = await c.post("/servers", json=payload)
            r.raise_for_status()
            return r.json()

    async def wait_for_ip(self, server_id: str, timeout: int = 300, poll_interval: int = 10) -> str:
        elapsed = 0
        while elapsed < timeout:
            server = await self.get_server(server_id)
            ip = server.get("ipv4") or server.get("ip")
            if ip:
                logger.info("Server %s got IP: %s", server_id, ip)
                return str(ip)
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"Server {server_id} did not get an IP within {timeout}s")

    async def delete_server(self, server_id: str) -> None:
        async with self._client() as c:
            r = await c.delete(f"/servers/{server_id}")
            r.raise_for_status()
        logger.info("BitLaunch server %s deleted", server_id)

    async def list_ssh_keys(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get("/ssh-keys")
            r.raise_for_status()
            data = r.json()
            return data.get("sshKeys", data) if isinstance(data, dict) else data

    async def create_ssh_key(self, name: str, public_key: str) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.post("/ssh-keys", json={"name": name, "publicKey": public_key})
            r.raise_for_status()
            return r.json()

    async def delete_ssh_key(self, key_id: str) -> None:
        async with self._client() as c:
            r = await c.delete(f"/ssh-keys/{key_id}")
            r.raise_for_status()

    async def list_hosts(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get("/hosts")
            r.raise_for_status()
            data = r.json()
            return data.get("hosts", data) if isinstance(data, dict) else data

    async def list_images(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get(f"/hosts/{self._host_id}/images")
            r.raise_for_status()
            data = r.json()
            return data.get("images", data) if isinstance(data, dict) else data

    async def list_sizes(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get(f"/hosts/{self._host_id}/sizes")
            r.raise_for_status()
            data = r.json()
            return data.get("sizes", data) if isinstance(data, dict) else data

    async def list_regions(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get(f"/hosts/{self._host_id}/regions")
            r.raise_for_status()
            data = r.json()
            return data.get("regions", data) if isinstance(data, dict) else data
