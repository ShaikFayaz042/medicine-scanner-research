from sqlalchemy.engine import make_url

from server import config as server_config
from server.database.models import Document, SchedulerConfig


def test_server_database_uses_local_modules():
    assert Document.__module__ == "server.database.models"
    assert SchedulerConfig.__module__ == "server.database.models"


def test_server_database_urls_follow_existing_fallback_policy():
    scraper_backend = (
        "sqlite"
        if server_config._should_use_sqlite_fallback(
            server_config.SCRAPER_DB_HOST,
            server_config.SCRAPER_DB_URI,
            server_config.APP_ENV,
        )
        else "postgresql"
    )
    assert make_url(server_config.DATABASE_URL).get_backend_name() == scraper_backend
    assert make_url(server_config.MEDICINE_DATABASE_URL).get_backend_name() == "postgresql"
