from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

_DEFAULT_XHTTP_PATH = "/xhttptransmissionpath"


def render_exit_node_config(
    clients: list[dict],
    x25519_private: str,
    short_ids: list[str],
    reality_sni: str,
    xray_api_port: int = 8080,
    xhttp_path: str = _DEFAULT_XHTTP_PATH,
    xhttp_host: str = "",
) -> str:
    tpl = _env.get_template("exit_node.json.j2")
    # xhttp_host: явный параметр > SNI (для XHTTP: host должен совпадать с SNI)
    effective_host = xhttp_host or reality_sni
    return tpl.render(
        clients=clients,
        x25519_private=x25519_private,
        short_ids=short_ids,
        reality_sni=reality_sni,
        xray_api_port=xray_api_port,
        xhttp_path=xhttp_path,
        xhttp_host=effective_host,
    )


def render_bridge_node_config(
    clients: list[dict],
    exit_node_ip: str,
    bridge_uuid: str,
    # exit-facing (proxy-exit outbound): REALITY-клиент к Exit на ключах Exit
    x25519_public: str,
    short_id: str,
    reality_sni: str,
    # bridge-facing (inbound-client): REALITY-сервер на собственных ключах Bridge
    bridge_x25519_private: str,
    bridge_short_ids: list[str],
    bridge_reality_sni: str,
    xhttp_path: str = _DEFAULT_XHTTP_PATH,
    xhttp_host: str = "",
    bridge_xhttp_path: str = _DEFAULT_XHTTP_PATH,
    bridge_xhttp_host: str = "",
) -> str:
    tpl = _env.get_template("bridge_node.json.j2")
    # XHTTP: host должен совпадать с SNI, если явно не задан.
    effective_host = xhttp_host or reality_sni
    bridge_effective_host = bridge_xhttp_host or bridge_reality_sni
    return tpl.render(
        clients=clients,
        exit_node_ip=exit_node_ip,
        bridge_uuid=bridge_uuid,
        x25519_public=x25519_public,
        short_id=short_id,
        reality_sni=reality_sni,
        bridge_x25519_private=bridge_x25519_private,
        bridge_short_ids=bridge_short_ids,
        bridge_reality_sni=bridge_reality_sni,
        xhttp_path=xhttp_path,
        xhttp_host=effective_host,
        bridge_xhttp_path=bridge_xhttp_path,
        bridge_xhttp_host=bridge_effective_host,
    )
