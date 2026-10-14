from server import config as server_config
from server.database.models import Document, SchedulerConfig


def test_server_database_uses_local_modules():
    assert Document.__module__ == "server.database.models"
    assert SchedulerConfig.__module__ == "server.database.models"


def test_development_falls_back_to_sqlite_for_remote_supabase_pooler_hosts():
    assert server_config._should_use_sqlite_fallback(
        "aws-0-ap-south-1.pooler.supabase.com",
        None,
        "development",
    ) is True
    assert server_config._should_use_sqlite_fallback("localhost", None, "development") is False
