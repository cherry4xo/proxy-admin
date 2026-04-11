import json
import time
from pathlib import Path

import httpx
import jwt

_IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
_JWT_TTL_SECONDS = 3600
_IAM_TOKEN_REFRESH_BEFORE_EXPIRY = 60


class ServiceAccountKey:
    def __init__(self, key_file_path: str) -> None:
        data = json.loads(Path(key_file_path).read_text())
        self._service_account_id: str = data["service_account_id"]
        self._key_id: str = data["id"]
        self._private_key: str = data["private_key"]

    def create_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "aud": _IAM_TOKEN_URL,
            "iss": self._service_account_id,
            "iat": now,
            "exp": now + _JWT_TTL_SECONDS,
        }
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="PS256",
            headers={"kid": self._key_id},
        )


class IamTokenProvider:
    def __init__(self, sa_key: ServiceAccountKey, verify_ssl: bool = True) -> None:
        self._sa_key = sa_key
        self._verify_ssl = verify_ssl
        self._token: str = ""
        self._expires_at: float = 0.0

    def _is_expired(self) -> bool:
        return time.time() >= self._expires_at - _IAM_TOKEN_REFRESH_BEFORE_EXPIRY

    async def get_token(self) -> str:
        if not self._is_expired():
            return self._token

        signed_jwt = self._sa_key.create_jwt()
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            response = await client.post(
                _IAM_TOKEN_URL,
                json={"jwt": signed_jwt},
            )
            response.raise_for_status()
            data = response.json()

        self._token = data["iamToken"]
        self._expires_at = time.time() + _JWT_TTL_SECONDS
        return self._token
