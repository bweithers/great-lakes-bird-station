# NUC Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full server-side bird detection pipeline on an Intel NUC — audio capture, BirdNET analysis, DuckDB ingest, and Cloudflare R2 export — driven by systemd timers and provisioned by a single setup script.

**Architecture:** Three systemd components run independently: a persistent `arecord` service writes 15-second WAV chunks to a staging directory; an analyze+ingest timer fires every 5 minutes, calling BirdNET-Analyzer then upserting results into DuckDB; an export timer fires every 30 minutes, dumping DuckDB to parquet, uploading to R2, and triggering a Vercel deploy hook. Python package `birdstation` provides the ingest and export logic. Configuration comes from a `.env` file on the NUC.

**Tech Stack:** Python 3.11+, DuckDB, BirdNET-Analyzer, boto3 (R2/S3-compatible), requests, pytest, systemd, arecord (ALSA)

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package definition, dependencies, entry points |
| `.gitignore` | Exclude recordings, results, .env, .duckdb |
| `birdstation/__init__.py` | Empty package marker |
| `birdstation/config.py` | Load env vars into a Config dataclass |
| `birdstation/db.py` | DuckDB connection + schema init |
| `birdstation/ingest.py` | Orchestrate analyze.py → parse CSV → upsert DuckDB → move WAVs |
| `birdstation/export.py` | DuckDB → parquet → R2 upload → deploy hook → purge old WAVs |
| `scripts/record.sh` | arecord loop (called by record service) |
| `systemd/birdstation-record.service` | Persistent arecord loop |
| `systemd/birdstation-analyze.service` | Runs birdstation-ingest entry point |
| `systemd/birdstation-analyze.timer` | Every 5 minutes |
| `systemd/birdstation-export.service` | Runs birdstation-export entry point |
| `systemd/birdstation-export.timer` | Every 30 minutes |
| `setup.sh` | Full NUC provisioner |
| `README.md` | Purpose + deployment instructions |
| `tests/test_config.py` | Config env var loading |
| `tests/test_db.py` | Schema creation |
| `tests/test_ingest.py` | CSV parsing, DuckDB upsert, file movement |
| `tests/test_export.py` | Row count check, parquet export, R2 mock, purge logic |

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `birdstation/__init__.py`
- Create: `recordings/new/.gitkeep`
- Create: `recordings/processed/.gitkeep`
- Create: `results/.gitkeep`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "birdstation"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "duckdb>=0.10.0",
    "boto3>=1.34.0",
    "requests>=2.31.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "moto[s3]>=5.0.0",
]

[project.scripts]
birdstation-ingest = "birdstation.ingest:run"
birdstation-export = "birdstation.export:run"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create .gitignore**

```gitignore
# Runtime data
recordings/new/*.wav
recordings/processed/*.wav
results/*.csv
*.duckdb
.env

# Python
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
```

- [ ] **Step 3: Create empty package and test markers**

```bash
touch birdstation/__init__.py tests/__init__.py
mkdir -p recordings/new recordings/processed results
touch recordings/new/.gitkeep recordings/processed/.gitkeep results/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore birdstation/__init__.py tests/__init__.py \
    recordings/new/.gitkeep recordings/processed/.gitkeep results/.gitkeep
git commit -m "chore: project scaffold"
```

---

## Task 2: Config

**Files:**
- Create: `birdstation/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import os
import pytest
from birdstation.config import Config, ConfigError


def test_config_loads_required_vars(monkeypatch):
    monkeypatch.setenv("BIRDSTATION_LAT", "43.05")
    monkeypatch.setenv("BIRDSTATION_LON", "-87.91")
    monkeypatch.setenv("BIRDSTATION_R2_ENDPOINT", "https://abc.r2.cloudflarestorage.com")
    monkeypatch.setenv("BIRDSTATION_R2_ACCESS_KEY", "key")
    monkeypatch.setenv("BIRDSTATION_R2_SECRET_KEY", "secret")
    monkeypatch.setenv("BIRDSTATION_R2_BUCKET", "birdstation")
    monkeypatch.setenv("BIRDSTATION_DEPLOY_HOOK_URL", "https://api.vercel.com/v1/integrations/deploy/hook")
    monkeypatch.setenv("BIRDSTATION_DUCKDB_PATH", "/tmp/birds.duckdb")
    monkeypatch.setenv("BIRDSTATION_RECORDINGS_DIR", "/tmp/recordings")
    monkeypatch.setenv("BIRDSTATION_BIRDNET_DIR", "/opt/BirdNET-Analyzer")

    cfg = Config.from_env()

    assert cfg.lat == 43.05
    assert cfg.lon == -87.91
    assert cfg.r2_bucket == "birdstation"
    assert cfg.duckdb_path == "/tmp/birds.duckdb"


def test_config_raises_on_missing_var(monkeypatch):
    for key in [
        "BIRDSTATION_LAT", "BIRDSTATION_LON", "BIRDSTATION_R2_ENDPOINT",
        "BIRDSTATION_R2_ACCESS_KEY", "BIRDSTATION_R2_SECRET_KEY",
        "BIRDSTATION_R2_BUCKET", "BIRDSTATION_DEPLOY_HOOK_URL",
        "BIRDSTATION_DUCKDB_PATH", "BIRDSTATION_RECORDINGS_DIR",
        "BIRDSTATION_BIRDNET_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigError):
        Config.from_env()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` (module doesn't exist yet)

- [ ] **Step 3: Implement config.py**

```python
# birdstation/config.py
import os
from dataclasses import dataclass


class ConfigError(Exception):
    pass


@dataclass
class Config:
    lat: float
    lon: float
    r2_endpoint: str
    r2_access_key: str
    r2_secret_key: str
    r2_bucket: str
    deploy_hook_url: str
    duckdb_path: str
    recordings_dir: str
    birdnet_dir: str
    min_confidence: float = 0.5

    @classmethod
    def from_env(cls) -> "Config":
        required = [
            "BIRDSTATION_LAT", "BIRDSTATION_LON",
            "BIRDSTATION_R2_ENDPOINT", "BIRDSTATION_R2_ACCESS_KEY",
            "BIRDSTATION_R2_SECRET_KEY", "BIRDSTATION_R2_BUCKET",
            "BIRDSTATION_DEPLOY_HOOK_URL", "BIRDSTATION_DUCKDB_PATH",
            "BIRDSTATION_RECORDINGS_DIR", "BIRDSTATION_BIRDNET_DIR",
        ]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        return cls(
            lat=float(os.environ["BIRDSTATION_LAT"]),
            lon=float(os.environ["BIRDSTATION_LON"]),
            r2_endpoint=os.environ["BIRDSTATION_R2_ENDPOINT"],
            r2_access_key=os.environ["BIRDSTATION_R2_ACCESS_KEY"],
            r2_secret_key=os.environ["BIRDSTATION_R2_SECRET_KEY"],
            r2_bucket=os.environ["BIRDSTATION_R2_BUCKET"],
            deploy_hook_url=os.environ["BIRDSTATION_DEPLOY_HOOK_URL"],
            duckdb_path=os.environ["BIRDSTATION_DUCKDB_PATH"],
            recordings_dir=os.environ["BIRDSTATION_RECORDINGS_DIR"],
            birdnet_dir=os.environ["BIRDSTATION_BIRDNET_DIR"],
            min_confidence=float(os.environ.get("BIRDSTATION_MIN_CONFIDENCE", "0.5")),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add birdstation/config.py tests/test_config.py
git commit -m "feat: config loading from env vars"
```

---

## Task 3: Database

**Files:**
- Create: `birdstation/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_db.py
import duckdb
import pytest
from birdstation.db import init_db, get_connection


def test_init_creates_detections_table(tmp_path):
    db_path = str(tmp_path / "test.duckdb")
    init_db(db_path)

    con = duckdb.connect(db_path)
    result = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'detections' ORDER BY column_name"
    ).fetchall()
    con.close()

    col_names = {row[0] for row in result}
    assert col_names == {"detected_at", "file_path", "common_name", "scientific_name", "confidence", "lat", "lon"}


def test_init_creates_export_log_table(tmp_path):
    db_path = str(tmp_path / "test.duckdb")
    init_db(db_path)

    con = duckdb.connect(db_path)
    result = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'export_log' ORDER BY column_name"
    ).fetchall()
    con.close()

    col_names = {row[0] for row in result}
    assert {"exported_at", "row_count"}.issubset(col_names)


def test_init_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.duckdb")
    init_db(db_path)
    init_db(db_path)  # second call must not raise
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_db.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement db.py**

```python
# birdstation/db.py
import duckdb


def get_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(db_path)


def init_db(db_path: str) -> None:
    con = get_connection(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            detected_at     TIMESTAMP,
            file_path       VARCHAR,
            common_name     VARCHAR,
            scientific_name VARCHAR,
            confidence      FLOAT,
            lat             FLOAT,
            lon             FLOAT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS export_log (
            exported_at TIMESTAMP DEFAULT current_timestamp,
            row_count   INTEGER
        )
    """)
    con.close()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_db.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add birdstation/db.py tests/test_db.py
git commit -m "feat: duckdb schema init"
```

---

## Task 4: Ingest

**Files:**
- Create: `birdstation/ingest.py`
- Create: `tests/test_ingest.py`

**Note on BirdNET output:** BirdNET-Analyzer writes one CSV per input WAV file to the output directory. Default filename: `<wav_stem>.BirdNET.results.csv`. Columns: `Start (s)`, `End (s)`, `Scientific name`, `Common name`, `Confidence`. Verify this on the NUC after BirdNET is installed — if the column names differ, update `parse_birdnet_csv()`.

WAV filenames must follow `YYYYMMDD_HHMMSS.wav` format (written by the record script). `detected_at` is derived as `recording_start + Start(s)` offset.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ingest.py
import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from birdstation.db import init_db
from birdstation.ingest import parse_birdnet_csv, upsert_detections, run_ingest


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.duckdb")
    init_db(db_path)
    return db_path


@pytest.fixture
def birdnet_csv(tmp_path):
    csv_path = tmp_path / "20260418_120000.BirdNET.results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Start (s)", "End (s)", "Scientific name", "Common name", "Confidence"])
        writer.writeheader()
        writer.writerow({"Start (s)": "0.0", "End (s)": "3.0", "Scientific name": "Turdus migratorius", "Common name": "American Robin", "Confidence": "0.95"})
        writer.writerow({"Start (s)": "3.0", "End (s)": "6.0", "Scientific name": "Cardinalis cardinalis", "Common name": "Northern Cardinal", "Confidence": "0.87"})
    return csv_path


def test_parse_birdnet_csv_returns_rows(birdnet_csv):
    rows = parse_birdnet_csv(birdnet_csv, wav_stem="20260418_120000", lat=43.05, lon=-87.91)

    assert len(rows) == 2
    assert rows[0]["common_name"] == "American Robin"
    assert rows[0]["scientific_name"] == "Turdus migratorius"
    assert abs(rows[0]["confidence"] - 0.95) < 0.001
    assert rows[0]["lat"] == 43.05
    assert rows[0]["lon"] == -87.91
    expected_dt = datetime(2026, 4, 18, 12, 0, 0) + timedelta(seconds=0.0)
    assert rows[0]["detected_at"] == expected_dt


def test_parse_birdnet_csv_empty_file(tmp_path):
    csv_path = tmp_path / "20260418_120000.BirdNET.results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Start (s)", "End (s)", "Scientific name", "Common name", "Confidence"])
        writer.writeheader()
    rows = parse_birdnet_csv(csv_path, wav_stem="20260418_120000", lat=43.05, lon=-87.91)
    assert rows == []


def test_upsert_detections_inserts_rows(tmp_db, birdnet_csv):
    rows = parse_birdnet_csv(birdnet_csv, wav_stem="20260418_120000", lat=43.05, lon=-87.91)
    upsert_detections(tmp_db, rows)

    con = duckdb.connect(tmp_db)
    count = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    con.close()
    assert count == 2


def test_upsert_detections_no_duplicates(tmp_db, birdnet_csv):
    rows = parse_birdnet_csv(birdnet_csv, wav_stem="20260418_120000", lat=43.05, lon=-87.91)
    upsert_detections(tmp_db, rows)
    upsert_detections(tmp_db, rows)  # second call with same data

    con = duckdb.connect(tmp_db)
    count = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    con.close()
    assert count == 2


def test_run_ingest_warns_on_empty_dir(tmp_path, tmp_db, caplog):
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    import logging
    with caplog.at_level(logging.WARNING):
        run_ingest(
            recordings_new=new_dir,
            recordings_processed=processed_dir,
            results_dir=tmp_path / "results",
            db_path=tmp_db,
            birdnet_dir=Path("/nonexistent"),  # won't be called
            lat=43.05, lon=-87.91,
            min_confidence=0.5,
        )

    assert any("no wav" in msg.lower() for msg in caplog.messages)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ingest.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement ingest.py**

```python
# birdstation/ingest.py
import csv
import logging
import shutil
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
    import dotenv
    dotenv.load_dotenv()
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
```

**Note:** Add `python-dotenv` to `pyproject.toml` dependencies:
```toml
"python-dotenv>=1.0.0",
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ingest.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add birdstation/ingest.py tests/test_ingest.py pyproject.toml
git commit -m "feat: birdnet csv parsing and duckdb ingest"
```

---

## Task 5: Export

**Files:**
- Create: `birdstation/export.py`
- Create: `tests/test_export.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_export.py
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from birdstation.db import get_connection, init_db
from birdstation.export import (
    count_new_rows,
    export_parquet,
    purge_old_processed,
    run_export,
)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.duckdb")
    init_db(db_path)
    return db_path


@pytest.fixture
def db_with_rows(tmp_db):
    con = get_connection(tmp_db)
    con.executemany(
        "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (datetime(2026, 4, 18, 12, 0, 0), "20260418_120000.wav", "American Robin", "Turdus migratorius", 0.95, 43.05, -87.91),
            (datetime(2026, 4, 18, 12, 5, 0), "20260418_120500.wav", "Northern Cardinal", "Cardinalis cardinalis", 0.87, 43.05, -87.91),
        ],
    )
    con.close()
    return tmp_db


def test_count_new_rows_returns_count_when_no_export_log(db_with_rows):
    count = count_new_rows(db_with_rows)
    assert count == 2


def test_count_new_rows_returns_zero_after_export_logged(db_with_rows):
    con = get_connection(db_with_rows)
    con.execute("INSERT INTO export_log (exported_at, row_count) VALUES (current_timestamp, 2)")
    con.close()

    # All rows are older than the export log entry — count should be 0
    count = count_new_rows(db_with_rows)
    assert count == 0


def test_export_parquet_creates_file(db_with_rows, tmp_path):
    out_path = tmp_path / "detections.parquet"
    export_parquet(db_with_rows, out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_purge_old_processed_removes_old_files(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    old_file = processed_dir / "old.wav"
    new_file = processed_dir / "new.wav"
    old_file.touch()
    new_file.touch()

    # backdate old_file modification time by 8 days
    old_mtime = time.time() - (8 * 24 * 3600)
    import os
    os.utime(old_file, (old_mtime, old_mtime))

    purge_old_processed(processed_dir, max_age_days=7)

    assert not old_file.exists()
    assert new_file.exists()


def test_run_export_warns_when_no_new_rows(tmp_db, tmp_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        run_export(
            db_path=tmp_db,
            parquet_path=tmp_path / "detections.parquet",
            processed_dir=tmp_path / "processed",
            r2_bucket="bucket",
            r2_endpoint="https://endpoint",
            r2_access_key="key",
            r2_secret_key="secret",
            deploy_hook_url="https://hook",
        )
    assert any("no new" in msg.lower() for msg in caplog.messages)


def test_run_export_uploads_and_triggers_hook(db_with_rows, tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    with patch("birdstation.export.boto3") as mock_boto3, \
         patch("birdstation.export.requests") as mock_requests:

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_requests.post.return_value = MagicMock(status_code=200)

        run_export(
            db_path=db_with_rows,
            parquet_path=tmp_path / "detections.parquet",
            processed_dir=processed_dir,
            r2_bucket="birdstation",
            r2_endpoint="https://abc.r2.cloudflarestorage.com",
            r2_access_key="key",
            r2_secret_key="secret",
            deploy_hook_url="https://api.vercel.com/v1/integrations/deploy/hook",
        )

        mock_s3.upload_file.assert_called_once()
        mock_requests.post.assert_called_once_with(
            "https://api.vercel.com/v1/integrations/deploy/hook"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_export.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement export.py**

```python
# birdstation/export.py
import logging
import os
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
    import dotenv
    dotenv.load_dotenv()
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_export.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add birdstation/export.py tests/test_export.py
git commit -m "feat: parquet export, r2 upload, and deploy hook trigger"
```

---

## Task 6: Record Script

**Files:**
- Create: `scripts/record.sh`

- [ ] **Step 1: Create record.sh**

```bash
#!/usr/bin/env bash
# Continuous arecord loop. Writes 15-second WAV chunks to $RECORDINGS_NEW_DIR.
# Called by birdstation-record.service. Set RECORDINGS_NEW_DIR in the environment.

set -euo pipefail

: "${RECORDINGS_NEW_DIR:?RECORDINGS_NEW_DIR must be set}"

echo "Starting recording loop → ${RECORDINGS_NEW_DIR}"

while true; do
    FILENAME="${RECORDINGS_NEW_DIR}/$(date +%Y%m%d_%H%M%S).wav"
    arecord \
        --device=plughw:CARD=Snowball,DEV=0 \
        --format=S16_LE \
        --rate=16000 \
        --channels=1 \
        --duration=15 \
        "$FILENAME" 2>/dev/null || true
done
```

**Note:** After setup, verify the Blue Snowball device name with `arecord -l`. If the card name differs from `Snowball`, update `--device` accordingly.

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/record.sh
git add scripts/record.sh
git commit -m "feat: arecord loop script"
```

---

## Task 7: Systemd Units

**Files:**
- Create: `systemd/birdstation-record.service`
- Create: `systemd/birdstation-analyze.service`
- Create: `systemd/birdstation-analyze.timer`
- Create: `systemd/birdstation-export.service`
- Create: `systemd/birdstation-export.timer`

- [ ] **Step 1: Create birdstation-record.service**

```ini
# systemd/birdstation-record.service
[Unit]
Description=Birdstation — continuous audio recorder
After=network.target

[Service]
Type=simple
User=birdstation
EnvironmentFile=/opt/birdstation/.env
ExecStart=/opt/birdstation/scripts/record.sh
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create birdstation-analyze.service**

```ini
# systemd/birdstation-analyze.service
[Unit]
Description=Birdstation — analyze recordings and ingest to DuckDB
After=network.target

[Service]
Type=oneshot
User=birdstation
WorkingDirectory=/opt/birdstation
EnvironmentFile=/opt/birdstation/.env
ExecStart=/opt/birdstation/.venv/bin/birdstation-ingest
StandardOutput=journal
StandardError=journal
```

- [ ] **Step 3: Create birdstation-analyze.timer**

```ini
# systemd/birdstation-analyze.timer
[Unit]
Description=Birdstation — run analyze+ingest every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit=birdstation-analyze.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Create birdstation-export.service**

```ini
# systemd/birdstation-export.service
[Unit]
Description=Birdstation — export parquet to R2 and trigger Vercel deploy
After=network.target

[Service]
Type=oneshot
User=birdstation
WorkingDirectory=/opt/birdstation
EnvironmentFile=/opt/birdstation/.env
ExecStart=/opt/birdstation/.venv/bin/birdstation-export
StandardOutput=journal
StandardError=journal
```

- [ ] **Step 5: Create birdstation-export.timer**

```ini
# systemd/birdstation-export.timer
[Unit]
Description=Birdstation — export every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Unit=birdstation-export.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 6: Commit**

```bash
git add systemd/
git commit -m "feat: systemd service and timer units"
```

---

## Task 8: Setup Script

**Files:**
- Create: `setup.sh`

- [ ] **Step 1: Create setup.sh**

```bash
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
    echo "==> Configure environment (press Enter to skip optional values)"
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
echo "    arecord -l                                  # confirm Snowball is visible"
echo "    systemctl status birdstation-record         # should be active (running)"
echo "    journalctl -u birdstation-analyze -f        # watch next ingest cycle"
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x setup.sh
git add setup.sh
git commit -m "feat: nuc provisioning script"
```

---

## Task 9: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

```markdown
# Great Lakes Bird Station

A home bird detection station running on an Intel NUC. Records audio via a Blue Snowball USB microphone, identifies species using BirdNET-Analyzer, stores detections in DuckDB, and publishes a public dashboard via Evidence.dev on Vercel.

## How It Works

```
arecord (continuous)
  → recordings/new/*.wav          (15-second chunks)

birdstation-analyze (every 5 min)
  → BirdNET-Analyzer analyze.py
  → detections → DuckDB

birdstation-export (every 30 min)
  → DuckDB → detections.parquet
  → Cloudflare R2
  → Vercel deploy hook → dashboard rebuild
```

## Hardware

- Intel NUC (x86_64, Ubuntu Server LTS)
- Blue Snowball USB microphone

## Deploying to a Fresh NUC

### 1. Prerequisites

- Ubuntu Server LTS installed
- SSH access
- Cloudflare R2 bucket created
- Vercel deploy hook URL from your Evidence dashboard project

### 2. Clone and provision

```bash
git clone https://github.com/<you>/great-lakes-bird-station.git
cd great-lakes-bird-station
sudo ./setup.sh
```

`setup.sh` will:
- Install system packages (Python, ffmpeg, ALSA tools, git)
- Clone and install BirdNET-Analyzer
- Install the `birdstation` Python package into a virtualenv
- Create the DuckDB database and schema
- Prompt for your R2 credentials, lat/lon, and Vercel deploy hook URL
- Install and start all systemd services

### 3. Verify

```bash
# Confirm the Blue Snowball is detected
arecord -l

# Check recording service
systemctl status birdstation-record

# Watch the first ingest cycle (fires ~5 min after boot)
journalctl -u birdstation-analyze -f

# Check DuckDB directly
duckdb /opt/birdstation/birds.duckdb "SELECT * FROM detections LIMIT 10"
```

### 4. Updating

```bash
ssh user@nuc
cd /opt/birdstation
git pull
sudo systemctl restart birdstation-analyze birdstation-export
```

## Development

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Cost

Effectively $0/month — Cloudflare R2 free tier (10GB / 10M reads), Vercel hobby tier.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: readme with purpose and deployment instructions"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| WSL dev, git deploy to NUC | Task 8 (setup.sh via git clone) + README |
| arecord 15s WAV chunks to recordings/new/ | Task 6 (record.sh) + Task 7 (record service) |
| Analyze every 5 min, warn if empty | Task 4 (run_ingest warns + returns), Task 7 (timer) |
| Ingest BirdNET CSV → DuckDB | Task 3 (schema) + Task 4 (parse + upsert) |
| No duplicate detections | Task 4 (upsert with EXISTS check) |
| Move WAVs to processed/ after ingest | Task 4 (wav.rename) |
| Export every 30 min, skip if no new rows | Task 5 (count_new_rows + warning) + Task 7 (timer) |
| DuckDB → parquet → R2 | Task 5 (export_parquet + boto3 upload) |
| Trigger Vercel deploy hook | Task 5 (requests.post) |
| Purge processed/ WAVs older than 7 days | Task 5 (purge_old_processed) |
| Full NUC provisioner from blank Ubuntu | Task 8 (setup.sh) |
| README with purpose + deployment | Task 9 |
| .gitignore for recordings, results, .env | Task 1 |

**No gaps found.**
