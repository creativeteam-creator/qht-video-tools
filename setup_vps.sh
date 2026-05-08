#!/bin/bash
# QHT Video Tools — VPS Setup Script (Ubuntu/Debian)
# VPS pe SSH se login karke yeh run karo:
#   chmod +x setup_vps.sh && ./setup_vps.sh

set -e

echo ""
echo "╔════════════════════════════════════════╗"
echo "║   QHT Video Tools — VPS Setup          ║"
echo "╚════════════════════════════════════════╝"
echo ""

# ── System update ──
echo "[1/6] System update..."
apt-get update -y && apt-get upgrade -y

# ── Python install ──
echo "[2/6] Python + pip install..."
apt-get install -y python3 python3-pip python3-venv git

# ── App directory ──
APP_DIR="/opt/qht-video-tools"
echo "[3/6] App directory: $APP_DIR"
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# ── If repo exists, pull. Otherwise clone. ──
if [ -d ".git" ]; then
    echo "Git repo found — pulling latest..."
    git pull
else
    echo "Enter your GitHub repo URL (e.g. https://github.com/youruser/yourrepo.git):"
    read -r REPO_URL
    git clone "$REPO_URL" .
fi

# ── Virtual environment ──
echo "[4/6] Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ── spaCy model ──
echo "[5/6] spaCy model download..."
python3 -m spacy download en_core_web_sm || echo "spaCy model download failed — basic tokenizer will be used"

# ── Secrets setup ──
echo "[6/6] Secrets setup..."
SECRETS_DIR="$APP_DIR/.streamlit"
mkdir -p "$SECRETS_DIR"
if [ ! -f "$SECRETS_DIR/secrets.toml" ]; then
    echo "OpenAI API key daalo:"
    read -r API_KEY
    echo "OPENAI_API_KEY = \"$API_KEY\"" > "$SECRETS_DIR/secrets.toml"
    echo "secrets.toml created ✓"
else
    echo "secrets.toml already exists ✓"
fi

# ── Systemd service ──
echo "Systemd service bana rahe hain..."
cat > /etc/systemd/system/qht-app.service << 'SERVICEEOF'
[Unit]
Description=QHT Video Tools (Streamlit)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/qht-video-tools
ExecStart=/opt/qht-video-tools/venv/bin/streamlit run app.py
Restart=always
RestartSec=5
Environment=STREAMLIT_SERVER_PORT=8501
Environment=STREAMLIT_SERVER_ADDRESS=0.0.0.0
Environment=STREAMLIT_SERVER_HEADLESS=true

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable qht-app
systemctl restart qht-app

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║   Setup Complete!                                  ║"
echo "║                                                    ║"
echo "║   App running at: http://$(hostname -I | awk '{print $1}'):8501  ║"
echo "║                                                    ║"
echo "║   Commands:                                        ║"
echo "║   systemctl status qht-app    — status dekho       ║"
echo "║   systemctl restart qht-app   — restart karo       ║"
echo "║   journalctl -u qht-app -f   — logs dekho          ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
