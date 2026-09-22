from server.database.models import Document, SchedulerConfig


def test_server_database_uses_local_modules():
    assert Document.__module__ == "server.database.models"
    assert SchedulerConfig.__module__ == "server.database.models"
