from dataclasses import dataclass

from bot.config import settings
from bot.database.base import async_session_factory
from bot.services.cloud.bitlaunch import BitLaunchClient
from bot.services.cloud.yandex import YandexClient
from bot.services.cloud.yandex_iam import IamTokenProvider, ServiceAccountKey
from bot.services.cloud.yandex_nlb import YandexNLBClient
from bot.services.node_service import NodeService
from bot.services.user_service import UserService


@dataclass
class Deps:
    node_service: NodeService
    user_service: UserService
    bitlaunch: BitLaunchClient
    yandex: YandexClient
    nlb: YandexNLBClient


def build_deps() -> Deps:
    bitlaunch = BitLaunchClient(
        api_token=settings.BITLAUNCH_API_TOKEN,
        host_id=settings.BITLAUNCH_HOST_ID,
        verify_ssl=settings.HTTPX_VERIFY,
    )
    sa_key = ServiceAccountKey(settings.YANDEX_SA_KEY_FILE)
    iam_provider = IamTokenProvider(sa_key=sa_key, verify_ssl=settings.HTTPX_VERIFY)
    yandex = YandexClient(
        folder_id=settings.YANDEX_FOLDER_ID,
        iam_provider=iam_provider,
        subnet_id=settings.YANDEX_SUBNET_ID,
        zone_id=settings.YANDEX_ZONE_ID,
        image_family=settings.YANDEX_IMAGE_FAMILY,
        verify_ssl=settings.HTTPX_VERIFY,
    )
    nlb = YandexNLBClient(
        folder_id=settings.YANDEX_FOLDER_ID,
        iam_provider=iam_provider,
        verify_ssl=settings.HTTPX_VERIFY,
    )
    node_service = NodeService(
        bitlaunch=bitlaunch,
        yandex=yandex,
        session_factory=async_session_factory,
    )
    user_service = UserService(session_factory=async_session_factory)
    return Deps(
        node_service=node_service,
        user_service=user_service,
        bitlaunch=bitlaunch,
        yandex=yandex,
        nlb=nlb,
    )
