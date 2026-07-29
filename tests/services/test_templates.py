import json

import pytest

from bot.templates import render_bridge_node_config, render_exit_node_config

_BASE = dict(
    clients=[{"uuid": "u1"}, {"uuid": "u2"}],
    exit_node_ip="9.9.9.9",
    bridge_uuid="bridge-uuid",
    x25519_public="EXITPUB",
    short_id="ab12",
    reality_sni="www.microsoft.com",
    bridge_x25519_private="BRIDGEPRIV",
    bridge_short_ids=["cd34", "ef56"],
)


def _inbound_reality(config_json: str) -> dict:
    d = json.loads(config_json)
    return d["inbounds"][0]["streamSettings"]["realitySettings"]


def test_legacy_render_uses_sni_dest():
    out = render_bridge_node_config(bridge_reality_sni="www.microsoft.com", **_BASE)
    rs = _inbound_reality(out)
    assert rs["dest"] == "www.microsoft.com:443"
    assert rs["serverNames"] == ["www.microsoft.com"]


def test_render_servernames_is_exactly_sni_no_www_sibling():
    # www-сиблинг убран: serverNames всегда ровно [sni] (эталон XTLS).
    out = render_bridge_node_config(bridge_reality_sni="dl.google.com", **_BASE)
    rs = _inbound_reality(out)
    assert rs["serverNames"] == ["dl.google.com"]
    assert "www.dl.google.com" not in rs["serverNames"]


def test_domain_render_uses_local_nginx_dest_and_single_servername():
    out = render_bridge_node_config(
        bridge_reality_sni="pr.cherry4xo.ru",
        bridge_reality_domain="pr.cherry4xo.ru",
        bridge_reality_dest="127.0.0.1:8443",
        **_BASE,
    )
    rs = _inbound_reality(out)
    assert rs["dest"] == "127.0.0.1:8443"
    assert rs["serverNames"] == ["pr.cherry4xo.ru"]
    # домен-режим не добавляет www.-сиблинг (серт выписан ровно на домен)
    assert "www.pr.cherry4xo.ru" not in rs["serverNames"]


def test_bridge_split_routing_ru_direct_rest_proxy():
    out = render_bridge_node_config(bridge_reality_sni="www.microsoft.com", **_BASE)
    d = json.loads(out)

    inbound = d["inbounds"][0]
    # sniffing включён для доменного матчинга (geosite), routeOnly — не переписывать dest
    assert inbound["sniffing"]["enabled"] is True
    assert inbound["sniffing"]["routeOnly"] is True

    rules = d["routing"]["rules"]
    tags = [r["outboundTag"] for r in rules]
    # порядок: bittorrent блок → RU по IP → RU по доменам → всё остальное на exit
    assert tags == ["blocked", "direct", "direct", "proxy-exit"]
    assert "geoip:ru" in rules[1]["ip"]
    assert rules[2]["domain"] == ["geosite:category-ru"]
    # catch-all proxy-exit обязан быть последним
    assert rules[-1]["inboundTag"] == ["inbound-client"]
    assert rules[-1]["outboundTag"] == "proxy-exit"


_EXIT_BASE = dict(
    clients=[{"uuid": "u1"}, {"uuid": "u2"}],
    x25519_private="EXITPRIV",
    short_ids=["ab12", "cd34"],
    reality_sni="www.microsoft.com",
)


def test_exit_render_without_warp_uses_plain_freedom():
    out = render_exit_node_config(**_EXIT_BASE)
    d = json.loads(out)

    tags = [o.get("tag") for o in d["outbounds"]]
    assert "direct" in tags
    assert "warp" not in tags
    # Без WARP — ни observatory, ни balancer.
    assert "observatory" not in d
    assert "balancers" not in d["routing"]
    # sniffing enabled с fakedns+quic для стабильности
    assert d["inbounds"][0]["sniffing"]["enabled"] is True
    assert "fakedns" in d["inbounds"][0]["sniffing"]["destOverride"]
    assert "quic" in d["inbounds"][0]["sniffing"]["destOverride"]


def test_exit_render_with_warp_adds_wireguard_balancer_observatory():
    out = render_exit_node_config(
        warp_enabled=True,
        warp_secret_key="WARPPRIV",
        warp_address=["172.16.0.2/32", "2606:4700:110::2/128"],
        warp_reserved="240,25,146",
        **_EXIT_BASE,
    )
    d = json.loads(out)

    warp = next(o for o in d["outbounds"] if o.get("tag") == "warp")
    assert warp["protocol"] == "wireguard"
    assert warp["settings"]["secretKey"] == "WARPPRIV"
    assert warp["settings"]["address"] == ["172.16.0.2/32", "2606:4700:110::2/128"]
    assert warp["settings"]["reserved"] == [240, 25, 146]
    assert warp["settings"]["peers"][0]["endpoint"] == "engage.cloudflareclient.com:2408"

    # observatory + balancer для fallback на direct.
    assert d["observatory"]["subjectSelector"] == ["warp", "direct"]
    balancer = d["routing"]["balancers"][0]
    assert balancer["selector"] == ["warp", "direct"]
    assert balancer["strategy"]["type"] == "leastPing"
    # catch-all правило уводит весь tcp/udp на балансер.
    rule = d["routing"]["rules"][-1]
    assert rule["balancerTag"] == "out"
    assert rule["network"] == "tcp,udp"


def test_outbound_proxy_exit_unchanged_in_domain_mode():
    out = render_bridge_node_config(
        bridge_reality_sni="pr.cherry4xo.ru",
        bridge_reality_domain="pr.cherry4xo.ru",
        bridge_reality_dest="127.0.0.1:8443",
        **_BASE,
    )
    d = json.loads(out)
    proxy_exit = next(o for o in d["outbounds"] if o.get("tag") == "proxy-exit")
    rs = proxy_exit["streamSettings"]["realitySettings"]
    # плечо bridge↔exit использует ключи/SNI exit — не затронуто доменом
    assert rs["publicKey"] == "EXITPUB"
    assert rs["serverName"] == "www.microsoft.com"
    # Vision flow for stable REALITY connection
    assert proxy_exit["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"


def test_proxy_exit_has_tcp_and_configurable_fingerprint():
    out = render_bridge_node_config(bridge_reality_sni="www.microsoft.com", fingerprint="firefox", **_BASE)
    d = json.loads(out)
    proxy_exit = next(o for o in d["outbounds"] if o.get("tag") == "proxy-exit")
    rs = proxy_exit["streamSettings"]["realitySettings"]
    tcp = proxy_exit["streamSettings"]["tcpSettings"]
    user = proxy_exit["settings"]["vnext"][0]["users"][0]
    # TCP transport (required for vision flow)
    assert proxy_exit["streamSettings"]["network"] == "tcp"
    assert tcp["header"]["type"] == "none"
    # Vision flow for stable REALITY (in user settings)
    assert user["flow"] == "xtls-rprx-vision"
    assert rs["fingerprint"] == "firefox"


def test_proxy_exit_fingerprint_defaults_to_chrome():
    out = render_bridge_node_config(bridge_reality_sni="www.microsoft.com", **_BASE)
    d = json.loads(out)
    rs = next(o for o in d["outbounds"] if o.get("tag") == "proxy-exit")[
        "streamSettings"
    ]["realitySettings"]
    assert rs["fingerprint"] == "chrome"
