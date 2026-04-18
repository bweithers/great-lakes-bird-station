# Great Lakes Bird Station — Design Spec

**Date:** 2026-04-18  
**Status:** Approved

---

## Purpose

A home bird detection station running on an Intel NUC. Records audio via a Blue Snowball USB mic, identifies birds using BirdNET-Analyzer, stores detections in DuckDB, and publishes a public dashboard via Evidence.dev on Vercel.

---

## Hardware

- **Intel NUC** — x86_64, Ubuntu Server LTS (blank install)
- **Blue Snowball USB mic** — plug-and-play on Linux via ALSA

---

## Repo Structure

```
great-lakes-bird-station/
├── birdstation/
│   ├── __init__.py
│   ├── config.py          # lat/lon, paths, R2 creds, deploy hook URL (from env)
│   ├── ingest.py          # BirdNET CSV output → DuckDB
│   └── export.py          # DuckDB → parquet → R2 → Vercel deploy hook
├── systemd/
│   ├── birdstation-record.service   # persistent arecord loop
│   ├── birdstation-analyze.service  # analyze.py + ingest
│   ├── birdstation-analyze.timer    # every 5 min
│   ├── birdstation-export.service   # export + deploy
│   └── birdstation-export.timer     # every 30 min
├── dashboard/             # Evidence.dev project (Vercel deploys from this subdir)
│   ├── pages/index.md
│   └── sources/birds.yaml
├── recordings/
│   ├── new/               # arecord writes here; analyze.py reads from here
│   └── processed/         # WAVs moved here after successful ingest
├── results/               # BirdNET CSV output (transient)
├── setup.sh               # Full NUC provisioner
├── README.md
└── pyproject.toml
```

---

## Pipeline

### Three systemd components

#### 1. Record (persistent service)
- `arecord` loops continuously, writing 15-second WAV chunks to `recordings/new/`
- Runs as a persistent service (not a timer) — restarts on failure

#### 2. Analyze + Ingest (timer: every 5 min)
1. Glob `recordings/new/` for WAV files
2. If none → log warning, exit (no-op)
3. Run `analyze.py --i recordings/new/ --o results/` (BirdNET writes CSV)
4. `ingest.py` reads CSV → upserts into DuckDB (keyed on `file_path + detected_at`)
5. Move processed WAVs from `recordings/new/` to `recordings/processed/`

#### 3. Export (timer: every 30 min)
1. Query DuckDB for new rows since last export timestamp
2. If zero → log warning, exit (no deploy triggered)
3. Export full table to `detections.parquet`
4. Upload to Cloudflare R2 via boto3 (S3-compatible)
5. POST to Vercel deploy hook URL
6. Purge `recordings/processed/` files older than 7 days

---

## Database Schema

```sql
CREATE TABLE detections (
    detected_at     TIMESTAMP,
    file_path       VARCHAR,
    common_name     VARCHAR,
    scientific_name VARCHAR,
    confidence      FLOAT,
    lat             FLOAT,
    lon             FLOAT
);
```

Stored in a local `.duckdb` file. No server required.

---

## Configuration

`config.py` reads from environment variables. A `.env` file on the NUC (not checked in) holds:

```
BIRDSTATION_LAT=
BIRDSTATION_LON=
BIRDSTATION_R2_ENDPOINT=
BIRDSTATION_R2_ACCESS_KEY=
BIRDSTATION_R2_SECRET_KEY=
BIRDSTATION_R2_BUCKET=
BIRDSTATION_DEPLOY_HOOK_URL=
BIRDSTATION_DUCKDB_PATH=
BIRDSTATION_RECORDINGS_DIR=
```

---

## NUC Provisioning (`setup.sh`)

1. `apt install` — python3, python3-venv, ffmpeg, alsa-utils, git
2. Clone BirdNET-Analyzer
3. Create Python venv, install `birdstation` package (pyproject.toml)
4. Create DuckDB file and apply schema
5. Create `recordings/new/` and `recordings/processed/` and `results/` dirs
6. Prompt for env vars → write `.env`
7. Install and enable systemd units
8. Start all services

Updates: `git pull && sudo systemctl restart birdstation-analyze birdstation-export`

---

## Dashboard (Evidence.dev)

Hosted on Vercel, deployed from `dashboard/` subdirectory. Data source: parquet from R2, downloaded at build time.

### Sections (single page)

1. **Species Leaderboard** — detection count, avg confidence, last seen; filterable by date range (7d / 30d / all)
2. **Activity Timeline** — detections per hour of day (bar chart) + detections per day over selected range
3. **Recent Detections** — last 50 rows; confidence color-coded (≥0.8 green, 0.5–0.8 yellow, <0.5 red)

Page header shows station name + `MAX(detected_at)` as last-updated timestamp.

**Build trigger:** NUC export script POSTs to Vercel deploy hook → Evidence rebuilds static site with latest parquet.

---

## Development Approach

- Develop on WSL (same x86_64 arch as NUC — no surprises at deploy time)
- Deploy to NUC via `git pull`
- Test audio capture and end-to-end pipeline on-device once pipeline code is ready

---

## Cost

Effectively $0/month.

| Service | Tier | Notes |
|---|---|---|
| Cloudflare R2 | Free | 10GB storage, 10M reads/month, no egress fees |
| Vercel | Hobby (free) | Dashboard hosting |
| Tailscale | Free | SSH access to NUC |
