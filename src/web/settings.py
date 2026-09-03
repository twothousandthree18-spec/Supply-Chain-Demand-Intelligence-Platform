"""Phase 6 web application settings (typed, 12-factor)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Phase 6 web/API layer.

    Database parameters default to the local warehouse (host 127.0.0.1,
    db supply_chain_intelligence, user postgres, trust auth) and are
    overridable via PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD environment
    variables, matching src/etl/db_utils.py.
    """

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    pghost: str = "127.0.0.1"
    pgport: str = "5432"
    pgdatabase: str = "supply_chain_intelligence"
    pguser: str = "postgres"
    pgpassword: str | None = None

    web_root: Path = Path(__file__).resolve().parent
    static_dir: Path = web_root / "static"

    default_page_size: int = 25
    max_page_size: int = 200

    @property
    def conninfo(self) -> dict:
        info = {
            "host": self.pghost,
            "port": self.pgport,
            "dbname": self.pgdatabase,
            "user": self.pguser,
        }
        if self.pgpassword:
            info["password"] = self.pgpassword
        return info


def get_settings() -> Settings:
    return Settings()