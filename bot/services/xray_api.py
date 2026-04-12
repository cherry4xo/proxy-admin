import logging

from bot.config import settings
from bot.services.ssh import SSHClient

logger = logging.getLogger(__name__)


class XrayApiClient:
    def __init__(self, host: str, api_port: int, ssh_client: SSHClient) -> None:
        self._host = host
        self._api_port = api_port
        self._ssh = ssh_client

    async def remove_user(self, inbound_tag: str, user_uuid: str) -> None:
        cmd = (
            f"xray api removeuser "
            f"--server=127.0.0.1:{self._api_port} "
            f"-tag={inbound_tag} "
            f"-email={user_uuid}"
        )
        stdout, stderr = await self._ssh.run_command(cmd)
        logger.info("remove_user on %s: %s %s", self._host, stdout.strip(), stderr.strip())
