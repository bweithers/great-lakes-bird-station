#!/usr/bin/env bash
# Provision a blank Ubuntu Server for Birdstation.
# Run as root: sudo ./setup.sh

set -euo pipefail

INSTALL_DIR=/opt/birdstation
BIRDNET_DIR=/opt/BirdNET-Analyzer
SERVICE_USER=birdstation

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    ffmpeg alsa-utils git curl

echo "==> Creating service user"
id "$SERVICE_USER" &>/dev/null || useradd --system --shell /bin/false "$SERVICE_USER"

echo "==> Installing BirdNET-Analyzer"
if [ ! -d "$BIRDNET_DIR" ]; then
    git clone https://github.com/kahst/BirdNET-Analyzer.git "$BIRDNET_DIR"
    python3 -m venv "$BIRDNET_DIR/.venv"
    "$BIRDNET_DIR/.venv/bin/pip" install -q -r "$BIRDNET_DIR/requirements.txt"
fi

echo "==> Installing birdstation package"
if [ ! -d "$INSTALL_DIR" ]; then
    cp -r . "$INSTALL_DIR"
fi
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q -e "$INSTALL_DIR"

echo "==> Creating directories"
mkdir -p "$INSTALL_DIR/recordings/new" \
         "$INSTALL_DIR/recordings/processed" \
         "$INSTALL_DIR/results"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/scripts/record.sh"

echo "==> Initialising database"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/python" -c "
from birdstation.db import init_db
init_db('$INSTALL_DIR/birds.duckdb')
print('Database initialised.')
"

if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "==> Configure environment"
    read -rp "Latitude (e.g. 43.05): " LAT
    read -rp "Longitude (e.g. -87.91): " LON
    read -rp "R2 endpoint URL: " R2_ENDPOINT
    read -rp "R2 access key: " R2_ACCESS_KEY
    read -rsp "R2 secret key: " R2_SECRET_KEY; echo
    read -rp "R2 bucket name: " R2_BUCKET
    read -rp "Vercel deploy hook URL: " DEPLOY_HOOK_URL

    cat > "$INSTALL_DIR/.env" <<EOF
BIRDSTATION_LAT=$LAT
BIRDSTATION_LON=$LON
BIRDSTATION_R2_ENDPOINT=$R2_ENDPOINT
BIRDSTATION_R2_ACCESS_KEY=$R2_ACCESS_KEY
BIRDSTATION_R2_SECRET_KEY=$R2_SECRET_KEY
BIRDSTATION_R2_BUCKET=$R2_BUCKET
BIRDSTATION_DEPLOY_HOOK_URL=$DEPLOY_HOOK_URL
BIRDSTATION_DUCKDB_PATH=$INSTALL_DIR/birds.duckdb
BIRDSTATION_RECORDINGS_DIR=$INSTALL_DIR/recordings
BIRDSTATION_BIRDNET_DIR=$BIRDNET_DIR
EOF
    chmod 600 "$INSTALL_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
fi

echo "==> Installing systemd units"
cp "$INSTALL_DIR/systemd/"*.service "$INSTALL_DIR/systemd/"*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now birdstation-record.service
systemctl enable --now birdstation-analyze.timer
systemctl enable --now birdstation-export.timer

echo
echo "==> Done. Verify with:"
echo "    arecord -l                          # confirm Snowball is visible"
echo "    systemctl status birdstation-record # should be active (running)"
echo "    journalctl -u birdstation-analyze -f # watch next ingest cycle"
