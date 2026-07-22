import logging

from bot.config import settings
from bot.services.ssh import SSHClient

logger = logging.getLogger(__name__)


class XrayApiClient:
    """Xray API client.
    
    NOTE: Xray v25+ НЕ поддерживает команды adduser/removeuser через CLI.
    Для управления пользователями используйте redeploy_node (через NodeService).
    Этот класс используется только для статистики и мониторинга.
    """
    
    def __init__(self, host: str, api_port: int, ssh_client: SSHClient) -> None:
        self._host = host
        self._api_port = api_port
        self._ssh = ssh_client

    async def get_stats(self) -> dict | None:
        """Получить статистику Xray (если доступна через API port)."""
        # TODO: Реализовать через HTTP stats API если нужно
        logger.debug("Stats API not implemented for Xray v25+")
        return None
