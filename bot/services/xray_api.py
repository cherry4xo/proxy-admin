import json
import logging

from bot.config import settings
from bot.services.ssh import SSHClient

logger = logging.getLogger(__name__)


class XrayApiClient:
    def __init__(self, host: str, api_port: int, ssh_client: SSHClient) -> None:
        self._host = host
        self._api_port = api_port
        self._ssh = ssh_client

    async def add_user(self, inbound_tag: str, user_uuid: str) -> None:
        payload = json.dumps({
            "tag": inbound_tag,
            "operation": {
                "type": "add",
                "user": {
                    "id": user_uuid,
                    "alterId": 0,
                    "security": "none",
                    "encryption": "none",
                    "flow": "xtls-rprx-vision",
                },
            },
        })
        cmd = (
            f"curl -s -X POST http://127.0.0.1:{self._api_port}/proxyman/alterInbound "
            f"-H 'Content-Type: application/json' "
            f"-d '{payload}'"
        )
        stdout, stderr = await self._ssh.run_command(cmd)
        logger.info("add_user response on %s: %s %s", self._host, stdout.strip(), stderr.strip())

    async def remove_user(self, inbound_tag: str, user_uuid: str) -> None:
        payload = json.dumps({
            "tag": inbound_tag,
            "operation": {
                "type": "remove",
                "email": user_uuid,
            },
        })
        cmd = (
            f"curl -s -X POST http://127.0.0.1:{self._api_port}/proxyman/alterInbound "
            f"-H 'Content-Type: application/json' "
            f"-d '{payload}'"
        )
        stdout, stderr = await self._ssh.run_command(cmd)
        logger.info("remove_user response on %s: %s %s", self._host, stdout.strip(), stderr.strip())
