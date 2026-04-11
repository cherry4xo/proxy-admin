import asyncio
import logging
from typing import Any

import httpx

from bot.services.cloud.yandex_iam import IamTokenProvider

logger = logging.getLogger(__name__)

_COMPUTE_BASE = "https://compute.api.cloud.yandex.net/compute/v1"
_OPERATION_BASE = "https://operation.api.cloud.yandex.net/operations"


class YandexClient:
    def __init__(
        self,
        folder_id: str,
        iam_provider: IamTokenProvider,
        subnet_id: str,
        zone_id: str,
        image_family: str,
        verify_ssl: bool = True,
    ) -> None:
        self._folder_id = folder_id
        self._iam = iam_provider
        self._subnet_id = subnet_id
        self._zone_id = zone_id
        self._image_family = image_family
        self._verify_ssl = verify_ssl

    async def _client(self) -> httpx.AsyncClient:
        token = await self._iam.get_token()
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            verify=self._verify_ssl,
        )

    async def list_instances(self) -> list[dict[str, Any]]:
        async with await self._client() as c:
            r = await c.get(
                f"{_COMPUTE_BASE}/instances",
                params={"folderId": self._folder_id},
            )
            r.raise_for_status()
            return r.json().get("instances", [])

    async def get_instance(self, instance_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get(f"{_COMPUTE_BASE}/instances/{instance_id}")
            r.raise_for_status()
            return r.json()

    def extract_ip(self, instance: dict[str, Any]) -> str | None:
        try:
            for iface in instance.get("networkInterfaces", []):
                ip = iface.get("primaryV4Address", {}).get("oneToOneNat", {}).get("address")
                if ip:
                    return str(ip)
        except (KeyError, IndexError, TypeError):
            pass
        return None

    async def create_instance(
        self,
        name: str,
        zone_id: str | None = None,
        subnet_id: str | None = None,
        platform_id: str = "standard-v3",
        cores: int = 2,
        memory_gb: int = 2,
        disk_size_gb: int = 20,
        image_family: str | None = None,
        image_folder_id: str = "standard-images",
        ssh_public_key: str = "",
        init_script: str = "",
    ) -> dict[str, Any]:
        effective_zone = zone_id or self._zone_id
        effective_subnet = subnet_id or self._subnet_id
        effective_family = image_family or self._image_family

        metadata: dict[str, str] = {}
        if ssh_public_key:
            metadata["ssh-keys"] = f"ubuntu:{ssh_public_key}"
        if init_script:
            metadata["user-data"] = init_script

        payload: dict[str, Any] = {
            "folderId": self._folder_id,
            "name": name,
            "zoneId": effective_zone,
            "platformId": platform_id,
            "resourcesSpec": {
                "cores": cores,
                "memory": memory_gb * 1024 * 1024 * 1024,
                "coreFraction": 100,
            },
            "bootDiskSpec": {
                "autoDelete": True,
                "diskSpec": {
                    "size": disk_size_gb * 1024 * 1024 * 1024,
                    "imageSpec": {
                        "imageFamily": effective_family,
                        "imageFolderId": image_folder_id,
                    },
                },
            },
            "networkInterfaceSpecs": [
                {
                    "subnetId": effective_subnet,
                    "primaryV4AddressSpec": {"oneToOneNatSpec": {"ipVersion": "IPV4"}},
                }
            ],
            "metadata": metadata,
        }

        async with await self._client() as c:
            r = await c.post(f"{_COMPUTE_BASE}/instances", json=payload)
            r.raise_for_status()
            return r.json()

    async def wait_for_operation(self, operation_id: str, timeout: int = 300, poll_interval: int = 10) -> dict[str, Any]:
        elapsed = 0
        async with await self._client() as c:
            while elapsed < timeout:
                r = await c.get(f"{_OPERATION_BASE}/{operation_id}")
                r.raise_for_status()
                op = r.json()
                if op.get("done"):
                    if "error" in op:
                        raise RuntimeError(f"YC operation failed: {op['error']}")
                    return op
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
        raise TimeoutError(f"YC operation {operation_id} did not complete within {timeout}s")

    async def wait_for_instance_ip(self, instance_id: str, timeout: int = 300, poll_interval: int = 10) -> str:
        elapsed = 0
        while elapsed < timeout:
            instance = await self.get_instance(instance_id)
            ip = self.extract_ip(instance)
            if ip:
                logger.info("YC instance %s got IP: %s", instance_id, ip)
                return ip
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"YC instance {instance_id} did not get an external IP within {timeout}s")

    async def delete_instance(self, instance_id: str) -> None:
        async with await self._client() as c:
            r = await c.delete(f"{_COMPUTE_BASE}/instances/{instance_id}")
            r.raise_for_status()
        logger.info("YC instance %s deletion initiated", instance_id)

    async def stop_instance(self, instance_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.post(f"{_COMPUTE_BASE}/instances/{instance_id}:stop")
            r.raise_for_status()
            return r.json()
