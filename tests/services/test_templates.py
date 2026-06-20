import json

import pytest

from bot.templates import render_bridge_node_config

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


def test_legacy_render_uses_sni_dest_and_www_sibling():
    out = render_bridge_node_config(bridge_reality_sni="www.microsoft.com", **_BASE)
    rs = _inbound_reality(out)
    assert rs["dest"] == "www.microsoft.com:443"
    # www.microsoft.com уже начинается с www. — сиблинг не добавляется
    assert rs["serverNames"] == ["www.microsoft.com"]


def test_legacy_render_non_www_sni_adds_sibling():
    out = render_bridge_node_config(bridge_reality_sni="example.com", **_BASE)
    rs = _inbound_reality(out)
    assert rs["serverNames"] == ["example.com", "www.example.com"]


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
    assert proxy_exit["settings"]["vnext"][0]["users"][0]["flow"] == ""
