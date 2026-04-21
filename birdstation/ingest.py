import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer

from birdstation.db import get_connection

logger = logging.getLogger(__name__)


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
    db_path: str,
    lat: float,
    lon: float,
    min_confidence: float,
) -> None:
    wavs = sorted(recordings_new.glob("*.wav"))
    if not wavs:
        logger.warning("No WAV files found in %s — skipping analyze+ingest", recordings_new)
        return

    analyzer = Analyzer()

    for wav in wavs:
        recording_start = datetime.strptime(wav.stem, "%Y%m%d_%H%M%S")
        rec = Recording(
            analyzer,
            str(wav),
            lat=lat,
            lon=lon,
            date=recording_start,
            min_conf=min_confidence,
        )
        rec.analyze()

        rows = [
            {
                "detected_at": recording_start + timedelta(seconds=d["start_time"]),
                "file_path": wav.name,
                "common_name": d["common_name"],
                "scientific_name": d["scientific_name"],
                "confidence": d["confidence"],
                "lat": lat,
                "lon": lon,
            }
            for d in rec.detections
        ]
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
        db_path=cfg.duckdb_path,
        lat=cfg.lat,
        lon=cfg.lon,
        min_confidence=cfg.min_confidence,
    )
