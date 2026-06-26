import logging

import asyncssh

from bot.services.keygen import decrypt

logger = logging.getLogger(__name__)

_XRAY_BIN = "/opt/xray/xray"
_CONFIG_PATH = "/opt/xray/conf/config.json"

# Xray-core НЕ поддерживает SIGHUP hot-reload — всегда полный рестарт процесса.
_SYSTEMD_RESTART_CMD = "systemctl restart xray && systemctl is-active --quiet xray"

_TLS_DIR = "/opt/xray/tls"

# nginx на bridge как реальный TLS-таргет для REALITY dest (127.0.0.1:8443).
# Серт приходит готовым (раскладывается ботом), certbot тут НЕ запускается.
_BRIDGE_NGINX_SCRIPT = """\
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

DOMAIN="{domain}"
CERT_DIR="{tls_dir}/${{DOMAIN}}"

apt-get update -y -q
apt-get install -y -q nginx

test -f "${{CERT_DIR}}/fullchain.pem"
test -f "${{CERT_DIR}}/privkey.pem"

cat > /etc/nginx/sites-available/reality-${{DOMAIN}}.conf << EOF
server {{
    listen 127.0.0.1:8443 ssl http2;
    server_name ${{DOMAIN}};
    ssl_certificate     ${{CERT_DIR}}/fullchain.pem;
    ssl_certificate_key ${{CERT_DIR}}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {{
        default_type text/html;
        return 200 '<!doctype html><title>${{DOMAIN}}</title><h1>${{DOMAIN}}</h1>';
    }}
}}
EOF
ln -sf /etc/nginx/sites-available/reality-${{DOMAIN}}.conf /etc/nginx/sites-enabled/reality-${{DOMAIN}}.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx
echo "NGINX_TLS_DONE"
"""

# Генерация Cloudflare WARP-профиля на ноде через wgcf (один статический бинарь).
# Печатает поля парсимо для бота; reserved вычисляется ботом из client_id (base64 → 3 байта).
_WARP_SETUP_SCRIPT = """\
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

WGCF_VER="{wgcf_version}"
mkdir -p /opt/xray/warp
cd /opt/xray/warp

if [ ! -x /usr/local/bin/wgcf ]; then
    curl -fsSLo /usr/local/bin/wgcf "https://github.com/ViRb3/wgcf/releases/download/v${{WGCF_VER}}/wgcf_${{WGCF_VER}}_linux_amd64"
    chmod +x /usr/local/bin/wgcf
fi

# Регистрируем аккаунт один раз (идемпотентно); затем генерим WG-профиль.
[ -f wgcf-account.toml ] || (yes | wgcf register >/dev/null 2>&1)
wgcf generate >/dev/null 2>&1

PRIV=$(grep -i 'PrivateKey' wgcf-profile.conf | head -n1 | awk -F'= *' '{{print $2}}')
ADDR=$(grep -i 'Address' wgcf-profile.conf | awk -F'= *' '{{print $2}}' | paste -sd, -)

echo "WARP_PRIV=${{PRIV}}"
echo "WARP_ADDR=${{ADDR}}"
echo "WARP_DONE"
"""

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

XRAY_VER="{xray_version}"
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
ExecReload=/bin/sh -c '/bin/systemctl restart xray'
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

    async def setup_xray(self, api_port: int = 8080, xray_version: str = "v25.12.8") -> str:
        script = _XRAY_SETUP_SCRIPT.format(api_port=api_port, xray_version=xray_version)
        stdout, stderr = await self.run_command(script)
        if "SETUP_DONE" not in stdout:
            raise RuntimeError(f"Xray setup failed:\n{stderr or stdout}")
        logger.info("Xray setup complete on %s", self._host)
        return stdout

    async def setup_warp(self, wgcf_version: str = "2.2.22") -> dict[str, object]:
        """Сгенерировать WARP-профиль на ноде через wgcf, вернуть параметры для Xray.

        Возвращает {"secret_key": str, "address": list[str], "reserved": str}.
        reserved дефолтит в "0,0,0" — рабочее значение, handshake проходит
        (точный client_id wgcf не сохраняет в account.toml).
        """
        script = _WARP_SETUP_SCRIPT.format(wgcf_version=wgcf_version)
        stdout, stderr = await self.run_command(script)
        if "WARP_DONE" not in stdout:
            raise RuntimeError(f"WARP setup failed:\n{stderr or stdout}")
        secret_key = ""
        address: list[str] = []
        for line in stdout.splitlines():
            if line.startswith("WARP_PRIV="):
                secret_key = line.split("=", 1)[1].strip()
            elif line.startswith("WARP_ADDR="):
                address = [a.strip() for a in line.split("=", 1)[1].split(",") if a.strip()]
        if not secret_key or not address:
            raise RuntimeError(f"Failed to parse WARP profile:\n{stdout}")
        logger.info("WARP profile generated on %s", self._host)
        return {"secret_key": secret_key, "address": address, "reserved": "0,0,0"}

    async def deploy_xray_config(
        self,
        config_json: str,
        xray_runtime: str = "systemd",
        config_remote_path: str = _CONFIG_PATH,
    ) -> None:
        # Xray запускается через systemd (не Docker — дорого по памяти).
        # xray_runtime сохранён в сигнатуре для обратной совместимости вызовов.
        backup_path = f"{config_remote_path}.bak"
        # 1. Бэкап текущего конфига (на первом деплое файла ещё нет — игнорируем ошибку).
        await self.run_command(f"cp -f {config_remote_path} {backup_path} 2>/dev/null || true")

        # 2. Заливаем новый конфиг.
        await self.upload_file(config_remote_path, config_json)

        # 3. Валидируем ДО рестарта рабочего процесса.
        stdout, stderr = await self.run_command(f"{_XRAY_BIN} -test -c {config_remote_path}")
        test_output = stdout + stderr
        if "Configuration OK" not in test_output:
            # Откатываемся и отдаём ошибку валидации боту.
            await self.run_command(
                f"test -f {backup_path} && mv -f {backup_path} {config_remote_path} || true"
            )
            raise RuntimeError(
                f"Xray config validation failed, rolled back:\n{test_output.strip()}"
            )

        # 4. Конфиг валиден — полный рестарт (Xray не умеет SIGHUP hot-reload).
        stdout, stderr = await self.run_command(_SYSTEMD_RESTART_CMD)
        logger.info("Xray restart on %s: %s %s", self._host, stdout.strip(), stderr.strip())

        # 5. Чистим бэкап после успеха.
        await self.run_command(f"rm -f {backup_path}")

    async def restart_xray(self) -> str:
        stdout, stderr = await self.run_command(_SYSTEMD_RESTART_CMD)
        logger.info("Xray manual restart on %s: %s %s", self._host, stdout.strip(), stderr.strip())
        return stdout or stderr

    async def deploy_tls_cert(self, fullchain: str, privkey: str, domain: str) -> None:
        cert_dir = f"{_TLS_DIR}/{domain}"
        await self.run_command(f"mkdir -p {cert_dir} && chmod 700 {_TLS_DIR} {cert_dir}")
        await self.upload_file(f"{cert_dir}/fullchain.pem", fullchain)
        await self.upload_file(f"{cert_dir}/privkey.pem", privkey)
        await self.run_command(f"chmod 600 {cert_dir}/fullchain.pem {cert_dir}/privkey.pem")
        logger.info("TLS cert for %s deployed to %s", domain, self._host)

    async def setup_bridge_nginx(self, domain: str) -> str:
        script = _BRIDGE_NGINX_SCRIPT.format(domain=domain, tls_dir=_TLS_DIR)
        stdout, stderr = await self.run_command(script)
        if "NGINX_TLS_DONE" not in stdout:
            raise RuntimeError(f"Bridge nginx setup failed:\n{stderr or stdout}")
        logger.info("Bridge nginx (%s) ready on %s", domain, self._host)
        return stdout
