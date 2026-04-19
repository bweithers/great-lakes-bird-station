import logging
import time
from pathlib import Path

import boto3
import requests

from birdstation.db import get_connection

logger = logging.getLogger(__name__)


def count_new_rows(db_path: str) -> int:
    con = get_connection(db_path)
    result = con.execute("""
        SELECT COUNT(*) FROM detections
        WHERE detected_at > COALESCE(
            (SELECT MAX(exported_at) FROM export_log),
            TIMESTAMP '1970-01-01'
        )
    """).fetchone()[0]
    con.close()
    return result


def export_parquet(db_path: str, parquet_path: Path) -> int:
    con = get_connection(db_path)
    con.execute(f"COPY detections TO '{parquet_path}' (FORMAT PARQUET)")
    row_count = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    con.execute(
        "INSERT INTO export_log (exported_at, row_count) VALUES (current_timestamp, ?)",
        [row_count],
    )
    con.close()
    return row_count


def purge_old_processed(processed_dir: Path, max_age_days: int = 7) -> None:
    cutoff = time.time() - (max_age_days * 24 * 3600)
    for wav in processed_dir.glob("*.wav"):
        if wav.stat().st_mtime < cutoff:
            wav.unlink()
            logger.info("Purged old recording: %s", wav.name)


def run_export(
    db_path: str,
    parquet_path: Path,
    processed_dir: Path,
    r2_bucket: str,
    r2_endpoint: str,
    r2_access_key: str,
    r2_secret_key: str,
    deploy_hook_url: str,
    max_age_days: int = 7,
) -> None:
    new_rows = count_new_rows(db_path)
    if new_rows == 0:
        logger.warning("No new detections since last export — skipping")
        return

    row_count = export_parquet(db_path, parquet_path)
    logger.info("Exported %d total rows to %s", row_count, parquet_path)

    s3 = boto3.client(
        "s3",
        endpoint_url=r2_endpoint,
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret_key,
        region_name="auto",
    )
    s3.upload_file(str(parquet_path), r2_bucket, "detections.parquet")
    logger.info("Uploaded parquet to R2 bucket %s", r2_bucket)

    requests.post(deploy_hook_url)
    logger.info("Triggered Vercel deploy hook")

    purge_old_processed(processed_dir, max_age_days)


def run() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from birdstation.config import Config
    cfg = Config.from_env()

    logging.basicConfig(level=logging.INFO)
    run_export(
        db_path=cfg.duckdb_path,
        parquet_path=Path("detections.parquet"),
        processed_dir=Path(cfg.recordings_dir) / "processed",
        r2_bucket=cfg.r2_bucket,
        r2_endpoint=cfg.r2_endpoint,
        r2_access_key=cfg.r2_access_key,
        r2_secret_key=cfg.r2_secret_key,
        deploy_hook_url=cfg.deploy_hook_url,
    )
