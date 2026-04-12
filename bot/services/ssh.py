import logging

import asyncssh

from bot.services.keygen import decrypt

logger = logging.getLogger(__name__)

_DOCKER_START_CMD = (
    "docker ps --filter name=xray --format '{{.Names}}' | grep -q xray "
    "&& docker restart xray "
    "|| docker run -d --name xray --restart always "
    "  -v /opt/xray/conf:/etc/xray "
    "  -p 443:443 -p 8080:8080 "
    "  teddysun/xray:latest"
)
_SYSTEMD_START_CMD = "systemctl is-active --quiet xray && systemctl restart xray || systemctl start xray"

_XRAY_SETUP_SCRIPT = """\
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -y -q
apt-get install -y -q curl jq unzip ufw

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 443/tcp
ufw allow {api_port}/tcp
ufw --force enable

mkdir -p /opt/xray/conf

XRAY_VER=$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq -r '.tag_name')
curl -fsSLo /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/download/${{XRAY_VER}}/Xray-linux-64.zip"
unzip -o /tmp/xray.zip xray -d /opt/xray
chmod +x /opt/xray/xray
rm /tmp/xray.zip

curl -fsSLo /opt/xray/geosite.dat "https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat"
curl -fsSLo /opt/xray/geoip.dat "https://github.com/v2fly/geoip/releases/latest/download/geoip.dat"

cat > /etc/systemd/system/xray.service << 'EOF'
[Unit]
Description=Xray Service
After=network.target

[Service]
ExecStart=/opt/xray/xray run -c /opt/xray/conf/config.json
Restart=on-failure
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

ln -sf /opt/xray/xray /usr/local/bin/xray

systemctl daemon-reload
systemctl enable xray
echo "SETUP_DONE"
"""


class SSHClient:
    def __init__(self, host: str, port: int, private_key_pem_encrypted: str) -> None:
        self._host = host
        self._port = port
        self._private_key_pem = decrypt(private_key_pem_encrypted)

    def _key(self) -> asyncssh.SSHKey:
        return asyncssh.import_private_key(self._private_key_pem)

    async def _connect(self) -> asyncssh.SSHClientConnection:
        return await asyncssh.connect(
            self._host,
            port=self._port,
            username="root",
            client_keys=[self._key()],
            known_hosts=None,
        )

    async def run_command(self, command: str) -> tuple[str, str]:
        async with await self._connect() as conn:
            result = await conn.run(command, check=False)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if result.returncode != 0:
                logger.warning("Command exited %d on %s: %s", result.returncode, self._host, stderr)
            return stdout, stderr

    async def upload_file(self, remote_path: str, content: str) -> None:
        async with await self._connect() as conn:
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(remote_path, "w") as f:
                    await f.write(content)
        logger.info("Uploaded file to %s:%s", self._host, remote_path)

    async def xray_status(self) -> str:
        commands = [
            "systemctl is-active xray 2>&1 || true",
            "ss -tlnp 2>/dev/null | grep -E '443|8080' || echo 'no ports'",
            "journalctl -u xray -n 10 --no-pager 2>/dev/null || true",
        ]
        stdout, _ = await self.run_command(" && echo '---' && ".join(commands))
        return stdout

    async def generate_x25519(self) -> tuple[str, str]:
        stdout, stderr = await self.run_command("/opt/xray/xray x25519")
        private_key = ""
        public_key = ""
        for line in stdout.splitlines():
            lower = line.lower()
            if "privatekey:" in lower or "private key:" in lower:
                private_key = line.split(":", 1)[1].strip()
            elif "publickey:" in lower or "public key:" in lower or "password (publickey):" in lower:
                public_key = line.split(":", 1)[1].strip()
        if not private_key or not public_key:
            raise RuntimeError(f"Failed to parse x25519 output:\n{stdout}\n{stderr}")
        return private_key, public_key

    async def setup_xray(self, api_port: int = 8080) -> str:
        script = _XRAY_SETUP_SCRIPT.format(api_port=api_port)
        stdout, stderr = await self.run_command(script)
        if "SETUP_DONE" not in stdout:
            raise RuntimeError(f"Xray setup failed:\n{stderr or stdout}")
        logger.info("Xray setup complete on %s", self._host)
        return stdout

    async def deploy_xray_config(
        self,
        config_json: str,
        xray_runtime: str = "systemd",
        config_remote_path: str = "/opt/xray/conf/config.json",
    ) -> None:
        await self.upload_file(config_remote_path, config_json)
        start_cmd = _DOCKER_START_CMD if xray_runtime == "docker" else _SYSTEMD_START_CMD
        stdout, stderr = await self.run_command(start_cmd)
        logger.info("Xray start/restart on %s: %s %s", self._host, stdout.strip(), stderr.strip())
