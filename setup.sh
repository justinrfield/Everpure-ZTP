#!/bin/bash
set -e

echo "=== File Server Setup ==="

# Resolve the directory this script lives in (works regardless of clone path)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run apt-get update once if apt-get is available
if command -v apt-get &>/dev/null; then
    echo "[+] Updating apt package lists..."
    apt-get update -qq
fi

# Install Flask if not present
if ! python3 -c "import flask" 2>/dev/null; then
    echo "[+] Installing Flask..."
    _installed=0
    if command -v dnf &>/dev/null; then
        dnf install -y python3-flask 2>/dev/null && _installed=1 || true
    fi
    if [ $_installed -eq 0 ] && command -v yum &>/dev/null; then
        yum install -y python3-flask 2>/dev/null && _installed=1 || true
    fi
    if [ $_installed -eq 0 ] && command -v apt-get &>/dev/null; then
        apt-get install -y python3-flask 2>/dev/null && _installed=1 || true
    fi
    if [ $_installed -eq 0 ]; then
        echo "[!] Package manager install failed — installing via pip..."
        # Ensure pip is available (Ubuntu splits it into python3-pip)
        if command -v apt-get &>/dev/null; then
            apt-get install -y python3-pip 2>/dev/null || true
        elif command -v dnf &>/dev/null; then
            dnf install -y python3-pip 2>/dev/null || true
        elif command -v yum &>/dev/null; then
            yum install -y python3-pip 2>/dev/null || true
        fi
        if command -v pip3 &>/dev/null; then
            pip3 install flask
        elif python3 -m pip --version &>/dev/null 2>&1; then
            python3 -m pip install flask
        else
            echo "[!] Could not install pip — trying ensurepip..."
            python3 -m ensurepip --upgrade
            python3 -m pip install flask
        fi
    fi
else
    echo "[+] Flask already installed."
fi

# Install dnsmasq if not present
if ! command -v dnsmasq &>/dev/null; then
    echo "[+] Installing dnsmasq..."
    if command -v dnf &>/dev/null; then
        dnf install -y dnsmasq
    elif command -v yum &>/dev/null; then
        yum install -y dnsmasq
    elif command -v apt-get &>/dev/null; then
        apt-get install -y dnsmasq
    else
        echo "[!] Could not install dnsmasq — install it manually."
    fi
else
    echo "[+] dnsmasq already installed."
fi

# Create files directory
mkdir -p "${SCRIPT_DIR}/files"
echo "[+] Files directory: ${SCRIPT_DIR}/files"

# Generate and install systemd service (paths derived from actual install location)
echo "[+] Installing systemd service..."
cat > /etc/systemd/system/fileserver.service <<EOF
[Unit]
Description=Everpure ZTP File Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
Environment=FILE_SERVER_ROOT=${SCRIPT_DIR}/files
ExecStart=/usr/bin/python3 ${SCRIPT_DIR}/app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable fileserver
systemctl restart fileserver

# Open firewall port
if command -v firewall-cmd &>/dev/null; then
    echo "[+] Opening port 8080 in firewall..."
    firewall-cmd --permanent --add-port=8080/tcp
    firewall-cmd --reload
elif command -v ufw &>/dev/null; then
    echo "[+] Opening port 8080 in ufw..."
    ufw allow 8080/tcp
else
    echo "[!] No firewall tool found — ensure port 8080 is open manually."
fi

echo ""
echo "=== Done ==="
systemctl status fileserver --no-pager
echo ""
echo "Access the file server at: http://$(hostname -I | awk '{print $1}'):8080/"
