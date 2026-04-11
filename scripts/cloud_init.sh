#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y curl jq unzip net-tools

XRAY_RUNTIME="${XRAY_RUNTIME:-systemd}"

if [ "$XRAY_RUNTIME" = "docker" ]; then
    apt-get install -y docker.io
    systemctl enable --now docker
    mkdir -p /opt/xray/conf
    docker pull teddysun/xray:latest
else
    XRAY_VER=$(curl -s https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq -r '.tag_name')
    curl -Lo /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VER}/Xray-linux-64.zip"
    unzip /tmp/xray.zip xray -d /opt/xray
    chmod +x /opt/xray/xray
    mkdir -p /opt/xray/conf

    cat > /etc/systemd/system/xray.service << 'EOF'
[Unit]
Description=Xray Service
After=network.target

[Service]
ExecStart=/opt/xray/xray run -c /opt/xray/conf/config.json
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable xray
fi
