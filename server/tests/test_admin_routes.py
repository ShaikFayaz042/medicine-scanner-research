from fastapi.testclient import TestClient

import server.routes.cloud_scheduler as cloud_scheduler
from server.main import app
from server.controllers import admin_controller

client = TestClient(app)


def test_scheduler_state_includes_time_fields(monkeypatch):
    class FakeClient:
        class exceptions:
            class ResourceNotFoundException(Exception):
                pass

        def get_schedule(self, Name):
            return {"Name": Name, "State": "ENABLED", "ScheduleExpression": "cron(15 2 * * ? *)"}

    monkeypatch.setattr(cloud_scheduler, "_scheduler_client", lambda: FakeClient())
    monkeypatch.setattr(cloud_scheduler, "EVENTBRIDGE_SCHEDULE_NAME", "test-schedule")

    state = cloud_scheduler.get_scheduler_state()

    assert state["enabled"] is True
    assert state["hour"] == 2
    assert state["minute"] == 15


def test_admin_dashboard_route(monkeypatch):
    monkeypatch.setattr(
        admin_controller,
        "get_dashboard_summary",
        lambda: {
            "total_documents": 12,
            "new_documents": 3,
            "downloaded": 8,
            "failed": 1,
            "last_scraper_run": "2026-09-20T10:00:00Z",
            "last_successful_run": "2026-09-20T09:45:00Z",
        },
    )

    response = client.get("/api/admin/dashboard")

    assert response.status_code == 200
    assert response.json()["total_documents"] == 12
    assert response.json()["new_documents"] == 3


def test_admin_scraper_status_route(monkeypatch):
    monkeypatch.setattr(
        admin_controller,
        "get_scraper_status",
        lambda: {
            "status": "idle",
            "last_run_time": "2026-09-20T10:00:00Z",
            "latest_result": {
                "scraped": 25,
                "new": 4,
                "downloaded": 3,
                "failed": 1,
                "skipped_existing": 7,
                "skipped_older": 5,
                "skipped_bad_date": 2,
            },
        },
    )

    response = client.get("/api/admin/scraper/status")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert response.json()["latest_result"]["new"] == 4


def test_admin_system_status_route(monkeypatch):
    monkeypatch.setattr(
        admin_controller,
        "get_system_status",
        lambda: {
            "api_health": "healthy",
            "database": "connected",
            "s3": "connected",
            "scheduler": "enabled",
        },
    )

    response = client.get("/api/admin/system")

    assert response.status_code == 200
    assert response.json()["api_health"] == "healthy"
    assert response.json()["database"] == "connected"
