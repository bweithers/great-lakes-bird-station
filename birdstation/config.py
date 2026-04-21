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
    min_confidence: float = 0.5

    @classmethod
    def from_env(cls) -> "Config":
        required = [
            "BIRDSTATION_LAT", "BIRDSTATION_LON",
            "BIRDSTATION_R2_ENDPOINT", "BIRDSTATION_R2_ACCESS_KEY",
            "BIRDSTATION_R2_SECRET_KEY", "BIRDSTATION_R2_BUCKET",
            "BIRDSTATION_DEPLOY_HOOK_URL", "BIRDSTATION_DUCKDB_PATH",
            "BIRDSTATION_RECORDINGS_DIR",
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
            min_confidence=float(os.environ.get("BIRDSTATION_MIN_CONFIDENCE", "0.5")),
        )
