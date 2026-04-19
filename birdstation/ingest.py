import csv
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from birdstation.db import get_connection

logger = logging.getLogger(__name__)


def parse_birdnet_csv(
    csv_path: Path,
    wav_stem: str,
    lat: float,
    lon: float,
) -> list[dict[str, Any]]:
    recording_start = datetime.strptime(wav_stem, "%Y%m%d_%H%M%S")
    rows = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append({
                "detected_at": recording_start + timedelta(seconds=float(row["Start (s)"])),
                "file_path": wav_stem + ".wav",
                "common_name": row["Common name"],
                "scientific_name": row["Scientific name"],
                "confidence": float(row["Confidence"]),
                "lat": lat,
                "lon": lon,
            })
    return rows


def upsert_detections(db_path: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    con = get_connection(db_path)
    con.execute("""
        CREATE TEMP TABLE IF NOT EXISTS _staging (
            detected_at TIMESTAMP, file_path VARCHAR,
            common_name VARCHAR, scientific_name VARCHAR,
            confidence FLOAT, lat FLOAT, lon FLOAT
        )
    """)
    con.executemany(
        "INSERT INTO _staging VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(r["detected_at"], r["file_path"], r["common_name"],
          r["scientific_name"], r["confidence"], r["lat"], r["lon"])
         for r in rows],
    )
    con.execute("""
        INSERT INTO detections
        SELECT s.* FROM _staging s
        WHERE NOT EXISTS (
            SELECT 1 FROM detections d
            WHERE d.file_path = s.file_path AND d.detected_at = s.detected_at
        )
    """)
    con.execute("DROP TABLE _staging")
    con.close()


def run_ingest(
    recordings_new: Path,
    recordings_processed: Path,
    results_dir: Path,
    db_path: str,
    birdnet_dir: Path,
    lat: float,
    lon: float,
    min_confidence: float,
) -> None:
    wavs = sorted(recordings_new.glob("*.wav"))
    if not wavs:
        logger.warning("No WAV files found in %s — skipping analyze+ingest", recordings_new)
        return

    results_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            sys.executable,
            str(birdnet_dir / "analyze.py"),
            "--i", str(recordings_new),
            "--o", str(results_dir),
            "--lat", str(lat),
            "--lon", str(lon),
            "--rtype", "csv",
            "--min_conf", str(min_confidence),
        ],
        check=True,
    )

    for wav in wavs:
        csv_path = results_dir / (wav.stem + ".BirdNET.results.csv")
        if csv_path.exists():
            rows = parse_birdnet_csv(csv_path, wav.stem, lat, lon)
            upsert_detections(db_path, rows)
        wav.rename(recordings_processed / wav.name)

    logger.info("Ingested %d WAV files", len(wavs))


def run() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from birdstation.config import Config
    cfg = Config.from_env()

    logging.basicConfig(level=logging.INFO)
    run_ingest(
        recordings_new=Path(cfg.recordings_dir) / "new",
        recordings_processed=Path(cfg.recordings_dir) / "processed",
        results_dir=Path("results"),
        db_path=cfg.duckdb_path,
        birdnet_dir=Path(cfg.birdnet_dir),
        lat=cfg.lat,
        lon=cfg.lon,
        min_confidence=cfg.min_confidence,
    )
