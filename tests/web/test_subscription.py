import base64

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.web.subscription import build_sub_app


@pytest.fixture()
async def client(mocker):
    # Мокаем сборку payload на уровне класса (build_sub_app создаёт UserService внутри).
    payload = (
        base64.b64encode(b"vless://1\nvless://2").decode(),
        {
            "Profile-Title": "base64:dGVzdA==",
            "Profile-Update-Interval": "12",
            "Subscription-Userinfo": "upload=0; download=0; total=0; expire=0",
        },
    )

    async def fake_payload(self, token):
        return payload if token == "valid" else None

    mocker.patch(
        "bot.services.user_service.UserService.get_subscription_payload",
        fake_payload,
    )
    app = build_sub_app()
    server = TestServer(app)
    cl = TestClient(server)
    await cl.start_server()
    yield cl
    await cl.close()


@pytest.mark.asyncio
async def test_healthz(client: TestClient):
    resp = await client.get("/healthz")
    assert resp.status == 200
    assert await resp.text() == "ok"


@pytest.mark.asyncio
async def test_sub_valid_token_returns_base64_and_headers(client: TestClient):
    resp = await client.get("/sub/valid")
    assert resp.status == 200
    body = await resp.text()
    assert base64.b64decode(body).decode() == "vless://1\nvless://2"
    assert resp.headers["Profile-Update-Interval"] == "12"
    assert "Subscription-Userinfo" in resp.headers


@pytest.mark.asyncio
async def test_sub_unknown_token_returns_404(client: TestClient):
    resp = await client.get("/sub/nope")
    assert resp.status == 404
