# Great Lakes Bird Station

A home bird detection station running on an Intel NUC. Records audio via a Blue Snowball USB microphone, identifies species using BirdNET-Analyzer, stores detections in DuckDB, and publishes a public dashboard via Evidence.dev on Vercel.

## How It Works

```
arecord (continuous)
  → recordings/new/*.wav          (15-second chunks)

birdstation-analyze (every 5 min)
  → BirdNET-Analyzer analyze.py
  → detections upserted into DuckDB

birdstation-export (every 30 min)
  → DuckDB → detections.parquet
  → Cloudflare R2
  → Vercel deploy hook → dashboard rebuild
```

## Hardware

- Intel NUC (x86_64, Ubuntu Server LTS)
- Blue Snowball USB microphone

## Deploying to a Fresh NUC

### Prerequisites

- Ubuntu Server LTS installed (Python 3.11+ required; 24.04 ships 3.12)
- SSH access to the NUC
- `alsa-utils` installed (`sudo apt install alsa-utils`) — verify mic with `arecord -l`
- Cloudflare R2 bucket created
- Vercel deploy hook URL from your Evidence dashboard project

### 1. Clone the repo

```bash
git clone https://github.com/<you>/great-lakes-bird-station.git
cd great-lakes-bird-station
```

### 2. Run the provisioner

```bash
sudo ./setup.sh
```

This will:
- Install system packages (Python, ffmpeg, ALSA tools, git)
- Clone and install BirdNET-Analyzer to `/opt/BirdNET-Analyzer`
- Install the `birdstation` Python package into a virtualenv at `/opt/birdstation/.venv`
- Create the DuckDB database and schema at `/opt/birdstation/birds.duckdb`
- Prompt for your R2 credentials, lat/lon, and Vercel deploy hook URL → writes `/opt/birdstation/.env`
- Install and start all systemd services

### 3. Verify

```bash
# Confirm the Blue Snowball is detected (note the card name — update record.sh if it differs from "Snowball")
arecord -l

# Check the recording service is running
systemctl status birdstation-record

# Watch the first ingest cycle (fires ~2 min after boot, then every 5 min)
journalctl -u birdstation-analyze -f

# Inspect detections directly
duckdb /opt/birdstation/birds.duckdb "SELECT * FROM detections ORDER BY detected_at DESC LIMIT 10"
```

### 4. Updating

```bash
ssh user@nuc
cd /opt/birdstation
sudo git pull
sudo systemctl restart birdstation-analyze birdstation-export
# birdstation-record restarts automatically via Restart=always
```

## Development

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Project Structure

```
birdstation/        Python package — config, db, ingest, export
scripts/            Shell scripts (record.sh — arecord loop)
systemd/            systemd unit and timer files
dashboard/          Evidence.dev dashboard (Vercel deploys from here)
setup.sh            Full NUC provisioner
```

## Cost

Effectively $0/month — Cloudflare R2 free tier (10GB storage, 10M reads/month, no egress fees), Vercel hobby tier.
