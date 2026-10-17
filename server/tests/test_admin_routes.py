from fastapi.testclient import TestClient

import server.deps as server_deps
import server.routes.cloud_scheduler as cloud_scheduler
from server import config as server_config
from server.database.mobile_models import User
from server.main import app
from server.services import admin_service
from server.routes import documents as documents_route

client = TestClient(app)


def test_documents_route_includes_processing_stage(monkeypatch):
    class FakeQuery:
        def all(self):
            from types import SimpleNamespace

            return [SimpleNamespace(
                id=1,
                document_id=123,
                source="cdsco_alerts",
                source_key="cdsco:123",
                document_type="alert",
                source_metadata={},
                title="Test document",
                release_date="2026-Jan-01",
                status="downloaded",
                processing_stage="profiled",
                file_size_bytes=100,
                pdf_url="https://example.test/test.pdf",
                local_file_path=None,
                created_at=None,
            )]

    class FakeDatabase:
        def query(self, model):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(documents_route, "SessionLocal", FakeDatabase)

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json()["documents"][0]["processing_stage"] == "profiled"


def test_scheduler_state_includes_time_fields(monkeypatch):
    class FakeClient:
        class exceptions:
            class ResourceNotFoundException(Exception):
                pass

        def get_schedule(self, Name):
            if Name == "test-schedule":
                return {"Name": Name, "State": "ENABLED", "ScheduleExpression": "cron(15 2 * * ? *)"}
            raise FakeClient.exceptions.ResourceNotFoundException()

    monkeypatch.setattr(cloud_scheduler, "_scheduler_client", lambda: FakeClient())
    monkeypatch.setattr(cloud_scheduler, "EVENTBRIDGE_SCHEDULE_NAME", "test-schedule")

    state = cloud_scheduler.get_scheduler_state()

    assert state["enabled"] is True
    assert state["hour"] == 2
    assert state["minute"] == 15


def test_run_now_passes_a_shared_run_id_to_ecs(monkeypatch):
    class FakeECS:
        def __init__(self):
            self.payload = None

        def run_task(self, **payload):
            self.payload = payload
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/test"}]}

    ecs = FakeECS()
    monkeypatch.setattr(cloud_scheduler, "_validate_aws_config", lambda: None)
    monkeypatch.setattr(cloud_scheduler, "_ecs_client", lambda: ecs)
    monkeypatch.setattr(cloud_scheduler, "_build_network_configuration", lambda: None)
    monkeypatch.setattr(cloud_scheduler, "set_worker_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(cloud_scheduler, "ECS_CLUSTER_NAME", "test-cluster")
    monkeypatch.setattr(cloud_scheduler, "ECS_TASK_DEFINITION", "test-task")
    monkeypatch.setattr(cloud_scheduler, "ECS_CONTAINER_NAME", "scraper")

    result = cloud_scheduler.run_scraper_now()

    command = ecs.payload["overrides"]["containerOverrides"][0]["command"]
    run_id_index = command.index("--run-id") + 1
    assert result["run_id"] == command[run_id_index]
    assert result["tasks"][0]["taskArn"].endswith("test")


def test_admin_dashboard_requires_allowlisted_admin(monkeypatch):
    monkeypatch.setattr(server_config, "ADMIN_EMAILS", ("admin@example.com",))

    guest = User(id="guest-user-id", name="Guest", email="user@example.com")
    admin = User(id="admin-user-id", name="Admin", email="admin@example.com")

    def override_guest_user():
        return guest

    def override_admin_user():
        return admin

    app.dependency_overrides[server_deps.get_current_user] = override_guest_user
    guest_response = client.get("/api/admin/dashboard")
    assert guest_response.status_code == 403
    assert guest_response.json()["detail"] == "Admin access required."

    app.dependency_overrides[server_deps.get_current_user] = override_admin_user
    admin_response = client.get("/api/admin/dashboard")
    assert admin_response.status_code == 200
    assert admin_response.json()["total_documents"] == 12

    app.dependency_overrides.clear()


def test_admin_dashboard_route(monkeypatch):
    monkeypatch.setattr(
        admin_service,
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
        admin_service,
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
        admin_service,
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
