import logging
from typing import Any

import httpx

from bot.services.cloud.yandex_iam import IamTokenProvider

logger = logging.getLogger(__name__)

_NLB_BASE = "https://load-balancer.api.cloud.yandex.net/load-balancer/v1"


class YandexNLBClient:
    def __init__(
        self,
        folder_id: str,
        iam_provider: IamTokenProvider,
        verify_ssl: bool = True,
    ) -> None:
        self._folder_id = folder_id
        self._iam = iam_provider
        self._verify_ssl = verify_ssl

    async def _client(self) -> httpx.AsyncClient:
        token = await self._iam.get_token()
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            verify=self._verify_ssl,
        )

    async def list_load_balancers(self) -> list[dict[str, Any]]:
        async with await self._client() as c:
            r = await c.get(f"{_NLB_BASE}/networkLoadBalancers", params={"folderId": self._folder_id})
            r.raise_for_status()
            return r.json().get("networkLoadBalancers", [])

    async def get_load_balancer(self, lb_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get(f"{_NLB_BASE}/networkLoadBalancers/{lb_id}")
            r.raise_for_status()
            return r.json()

    async def create_load_balancer(
        self,
        name: str,
        region_id: str = "ru-central1",
        listener_name: str = "proxy",
        listener_port: int = 443,
        target_group_id: str = "",
        health_check_port: int = 443,
    ) -> dict[str, Any]:
        attached_target_groups = []
        if target_group_id:
            attached_target_groups = [{
                "targetGroupId": target_group_id,
                "healthChecks": [{
                    "name": "tcp-check",
                    "interval": "2s",
                    "timeout": "1s",
                    "unhealthyThreshold": 2,
                    "healthyThreshold": 2,
                    "tcpOptions": {"port": health_check_port},
                }],
            }]

        payload: dict[str, Any] = {
            "folderId": self._folder_id,
            "name": name,
            "regionId": region_id,
            "type": "EXTERNAL",
            "listenerSpecs": [{
                "name": listener_name,
                "port": listener_port,
                "protocol": "TCP",
                "externalAddressSpec": {"ipVersion": "IPV4"},
            }],
            "attachedTargetGroups": attached_target_groups,
        }

        async with await self._client() as c:
            r = await c.post(f"{_NLB_BASE}/networkLoadBalancers", json=payload)
            r.raise_for_status()
            return r.json()

    async def delete_load_balancer(self, lb_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.delete(f"{_NLB_BASE}/networkLoadBalancers/{lb_id}")
            r.raise_for_status()
            return r.json()

    async def list_target_groups(self) -> list[dict[str, Any]]:
        async with await self._client() as c:
            r = await c.get(f"{_NLB_BASE}/targetGroups", params={"folderId": self._folder_id})
            r.raise_for_status()
            return r.json().get("targetGroups", [])

    async def get_target_group(self, tg_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get(f"{_NLB_BASE}/targetGroups/{tg_id}")
            r.raise_for_status()
            return r.json()

    async def add_targets(self, tg_id: str, targets: list[dict[str, str]]) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.post(
                f"{_NLB_BASE}/targetGroups/{tg_id}:addTargets",
                json={"targets": targets},
            )
            r.raise_for_status()
            return r.json()

    async def remove_targets(self, tg_id: str, targets: list[dict[str, str]]) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.post(
                f"{_NLB_BASE}/targetGroups/{tg_id}:removeTargets",
                json={"targets": targets},
            )
            r.raise_for_status()
            return r.json()

    async def create_target_group(self, name: str, targets: list[dict[str, str]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "folderId": self._folder_id,
            "name": name,
            "targets": targets or [],
        }
        async with await self._client() as c:
            r = await c.post(f"{_NLB_BASE}/targetGroups", json=payload)
            r.raise_for_status()
            return r.json()

    async def delete_target_group(self, tg_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.delete(f"{_NLB_BASE}/targetGroups/{tg_id}")
            r.raise_for_status()
            return r.json()

    async def attach_target_group(
        self,
        lb_id: str,
        tg_id: str,
        health_check_port: int = 443,
    ) -> dict[str, Any]:
        payload = {
            "attachedTargetGroup": {
                "targetGroupId": tg_id,
                "healthChecks": [{
                    "name": "tcp-check",
                    "interval": "2s",
                    "timeout": "1s",
                    "unhealthyThreshold": 2,
                    "healthyThreshold": 2,
                    "tcpOptions": {"port": health_check_port},
                }],
            }
        }
        async with await self._client() as c:
            r = await c.post(f"{_NLB_BASE}/networkLoadBalancers/{lb_id}:attachTargetGroup", json=payload)
            r.raise_for_status()
            return r.json()

    async def detach_target_group(self, lb_id: str, tg_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.post(
                f"{_NLB_BASE}/networkLoadBalancers/{lb_id}:detachTargetGroup",
                json={"targetGroupId": tg_id},
            )
            r.raise_for_status()
            return r.json()

    async def get_target_states(self, lb_id: str, tg_id: str) -> list[dict[str, Any]]:
        async with await self._client() as c:
            r = await c.get(
                f"{_NLB_BASE}/networkLoadBalancers/{lb_id}:getTargetStates",
                params={"targetGroupId": tg_id},
            )
            r.raise_for_status()
            return r.json().get("targetStates", [])
