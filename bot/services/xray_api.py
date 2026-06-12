import logging

from bot.config import settings
from bot.services.ssh import SSHClient

logger = logging.getLogger(__name__)


class XrayApiClient:
    def __init__(self, host: str, api_port: int, ssh_client: SSHClient) -> None:
        self._host = host
        self._api_port = api_port
        self._ssh = ssh_client

    async def add_user(self, inbound_tag: str, user_uuid: str, flow: str = "") -> None:
        # Горячее добавление клиента в работающий Xray без рестарта процесса.
        users_json = (
            '[{"user":{"vless":{"id":"%s","flow":"%s"}},"email":"%s"}]'
            % (user_uuid, flow, user_uuid)
        )
        cmd = (
            f"xray api adduser "
            f"--server=127.0.0.1:{self._api_port} "
            f"-tag={inbound_tag} "
            f"-users='{users_json}'"
        )
        stdout, stderr = await self._ssh.run_command(cmd)
        combined = (stdout + stderr).lower()
        if "error" in combined or "failed" in combined:
            raise RuntimeError(f"adduser failed: {(stdout + stderr).strip()}")
        logger.info("add_user on %s: %s %s", self._host, stdout.strip(), stderr.strip())

    async def remove_user(self, inbound_tag: str, user_uuid: str) -> None:
        cmd = (
            f"xray api removeuser "
            f"--server=127.0.0.1:{self._api_port} "
            f"-tag={inbound_tag} "
            f"-email={user_uuid}"
        )
        stdout, stderr = await self._ssh.run_command(cmd)
        logger.info("remove_user on %s: %s %s", self._host, stdout.strip(), stderr.strip())
