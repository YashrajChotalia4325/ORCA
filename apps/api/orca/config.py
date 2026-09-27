"""Runtime configuration, read from environment variables only.

Credentials are never hard-coded and never logged. See .env.example.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    v = _env(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


class Settings(BaseModel):
    default_mode: str = "LIVE"
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path = REPO_ROOT / "data" / "orca.db"
    replay_snapshot: str = "latest"

    # security
    auth_required: bool = False
    api_tokens: dict[str, str] = {}          # token -> role
    rate_limit_per_min: int = 60
    store_precise_location: bool = False
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # LLM (optional)
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5"
    llm_enabled: bool = True

    # monitoring
    monitor_enabled: bool = True
    monitor_interval_s: int = 900

    # http
    http_timeout_s: float = 15.0
    user_agent: str = "ORCA-prototype/0.1 (SIH26176 marine decision-support research prototype)"

    # credentials for adapters (presence only is reported, never values)
    mosdac_username: str | None = None
    mosdac_password: str | None = None
    copernicus_username: str | None = None
    copernicus_password: str | None = None
    imd_api_key: str | None = None
    protected_planet_token: str | None = None
    earthdata_token: str | None = None
    bhuvan_token: str | None = None
    incois_pfz_url: str | None = None
    incois_osf_url: str | None = None

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)


def _parse_tokens(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if ":" in part:
            tok, role = part.split(":", 1)
            if tok.strip():
                out[tok.strip()] = role.strip()
    return out


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(_env("ORCA_DATA_DIR", str(REPO_ROOT / "data")))
    return Settings(
        default_mode=(_env("ORCA_MODE", "LIVE") or "LIVE").upper(),
        data_dir=data_dir,
        db_path=Path(_env("ORCA_DB_PATH", str(data_dir / "orca.db"))),
        replay_snapshot=_env("ORCA_REPLAY_SNAPSHOT", "latest"),
        auth_required=_bool("ORCA_AUTH_REQUIRED", False),
        api_tokens=_parse_tokens(_env("ORCA_API_TOKENS")),
        rate_limit_per_min=int(_env("ORCA_RATE_LIMIT_PER_MIN", "60")),
        store_precise_location=_bool("ORCA_STORE_PRECISE_LOCATION", False),
        cors_origins=[o.strip() for o in (_env("ORCA_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000") or "").split(",") if o.strip()],
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        llm_model=_env("ORCA_LLM_MODEL", "claude-opus-5"),
        llm_enabled=_bool("ORCA_LLM_ENABLED", True),
        monitor_enabled=_bool("ORCA_MONITOR_ENABLED", True),
        monitor_interval_s=int(_env("ORCA_MONITOR_INTERVAL_S", "900")),
        http_timeout_s=float(_env("ORCA_HTTP_TIMEOUT_S", "15")),
        mosdac_username=_env("MOSDAC_USERNAME"),
        mosdac_password=_env("MOSDAC_PASSWORD"),
        copernicus_username=_env("COPERNICUSMARINE_SERVICE_USERNAME"),
        copernicus_password=_env("COPERNICUSMARINE_SERVICE_PASSWORD"),
        imd_api_key=_env("IMD_API_KEY"),
        protected_planet_token=_env("PROTECTED_PLANET_TOKEN"),
        earthdata_token=_env("EARTHDATA_TOKEN"),
        bhuvan_token=_env("BHUVAN_TOKEN"),
        incois_pfz_url=_env("INCOIS_PFZ_GEOJSON_URL"),
        incois_osf_url=_env("INCOIS_OSF_JSON_URL"),
    )
