#!/bin/bash

set -e

echo "========================================="
echo "ETH Trading Bot Deployment Script"
echo "========================================="

APP_DIR="/opt/trading-bot"
SERVICE_NAME="trading-bot"
REPO_URL="${1:-}"

if [ "$EUID" -eq 0 ]; then
    echo "ERROR: Do not run as root"
    exit 1
fi

echo "[1/6] Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "Python3 not found. Installing..."
    sudo apt-get update && sudo apt-get install -y python3 python3-pip
fi

python3 --version

echo "[2/6] Creating application directory..."
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

echo "[3/6] Cloning repository..."
if [ -n "$REPO_URL" ]; then
    if [ -d "$APP_DIR/.git" ]; then
        echo "Repository already exists, pulling latest..."
        cd $APP_DIR && git pull
    else
        git clone "$REPO_URL" $APP_DIR
    fi
else
    echo "No repository URL provided. Please manually copy files to $APP_DIR"
fi

echo "[4/6] Installing Python dependencies..."
cd $APP_DIR
pip3 install -r requirements.txt

echo "[5/6] Creating .env file..."
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/.env.example" ]; then
        cp $APP_DIR/.env.example $APP_DIR/.env
        echo "Created .env from .env.example"
        echo "Please edit $APP_DIR/.env and add your API keys"
    else
        echo "Warning: .env.example not found"
    fi
fi

echo "[6/6] Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=ETH Trading Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment=PATH=/home/$USER/.local/bin:$PATH
ExecStart=/usr/bin/python3 $APP_DIR/main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""
echo "Commands:"
echo "  Start bot:    sudo systemctl start $SERVICE_NAME"
echo "  Stop bot:     sudo systemctl stop $SERVICE_NAME"
echo "  View logs:    sudo journalctl -u $SERVICE_NAME -f"
echo "  Check status: sudo systemctl status $SERVICE_NAME"
echo ""
echo "Before starting, edit $APP_DIR/.env with your API keys"