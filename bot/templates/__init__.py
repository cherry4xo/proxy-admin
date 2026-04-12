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
    x25519_public: str,
    short_id: str,
    reality_sni: str,
    xhttp_path: str = _DEFAULT_XHTTP_PATH,
    xhttp_host: str = "",
) -> str:
    tpl = _env.get_template("bridge_node.json.j2")
    effective_host = xhttp_host or reality_sni
    return tpl.render(
        clients=clients,
        exit_node_ip=exit_node_ip,
        bridge_uuid=bridge_uuid,
        x25519_public=x25519_public,
        short_id=short_id,
        reality_sni=reality_sni,
        xhttp_path=xhttp_path,
        xhttp_host=effective_host,
    )
