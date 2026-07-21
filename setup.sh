#!/bin/bash
set -e

echo "=== File Server Setup ==="

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
        echo "[!] Package manager install failed — bootstrapping pip..."
        python3 -m ensurepip --upgrade
        python3 -m pip install flask
    fi
else
    echo "[+] Flask already installed."
fi

# Create files directory
mkdir -p /home/atcadmin/fileserver/files
echo "[+] Files directory: /home/atcadmin/fileserver/files"

# Install and start systemd service
echo "[+] Installing systemd service..."
cp /home/atcadmin/fileserver/fileserver.service /etc/systemd/system/fileserver.service
systemctl daemon-reload
systemctl enable fileserver
systemctl restart fileserver

# Open firewall port
if command -v firewall-cmd &>/dev/null; then
    echo "[+] Opening port 8080 in firewall..."
    firewall-cmd --permanent --add-port=8080/tcp
    firewall-cmd --reload
else
    echo "[!] firewall-cmd not found — ensure port 8080 is open in your firewall."
fi

echo ""
echo "=== Done ==="
systemctl status fileserver --no-pager
echo ""
echo "Access the file server at: http://$(hostname -I | awk '{print $1}'):8080/"
