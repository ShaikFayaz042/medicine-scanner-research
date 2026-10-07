"""Tests for pipeline event parsing (EventBridge envelope → ParsedEvent)."""
import json

from botocore.exceptions import ClientError

from server.pipeline.events import parse_pipeline_event


def test_parse_sfn_state_change():
    """Real input: EventBridge SNS envelope from SQS for SFN state change."""
    payload = {
        "MessageId": "test-msg-001",
        "source": "aws.states",
        "detail-type": "Step Functions Execution Status Change",
        "time": "2026-10-07T05:00:00Z",
        "detail": {
            "executionArn": (
                "arn:aws:states:ap-south-1:449902674528:"
                "execution:pdf-ingestion-pipeline:run-123"
            ),
            "stateMachineArn": (
                "arn:aws:states:ap-south-1:449902674528:"
                "stateMachine:pdf-ingestion-pipeline"
            ),
            "status": "SUCCEEDED",
        },
    }

    event = parse_pipeline_event(payload)

    assert event["run_id"] == "run-123"
    assert event["event_type"] == "sfn.state_change"
    assert event["source"] == "aws.states"
    assert event["status"] == "SUCCEEDED"
    assert event["event_id"] == "test-msg-001"
    assert event["payload"] == payload


def test_parse_ecs_task_failure():
    """Real input: EventBridge envelope for ECS task failure with --run-id in override."""
    payload = {
        "MessageId": "test-msg-002",
        "source": "aws.ecs",
        "detail-type": "ECS Task State Change",
        "time": "2026-10-07T05:51:42Z",
        "detail": {
            "clusterArn": (
                "arn:aws:ecs:ap-south-1:449902674528:"
                "cluster/medicine-scanner-cluster"
            ),
            "lastStatus": "STOPPED",
            "stopCode": "TaskFailedToStart",
            "overrides": {
                "containerOverrides": [{
                    "name": "data-processor",
                    "command": [
                        "python", "-m", "data_processing_service.main",
                        "--run-id", "run-xyz",
                        "--manifest-s3-key", "medicine-data-storage/processed_files/runs/run-xyz/manifest.json",
                    ],
                }],
            },
            "containers": [{
                "name": "data-processor",
                "exitCode": 1,
            }],
        },
    }

    event = parse_pipeline_event(payload)

    assert event["run_id"] == "run-xyz"
    assert event["event_type"] == "ecs.task_state_change"
    assert event["source"] == "aws.ecs"


def test_parse_unknown_source():
    """Unknown source should be handled gracefully."""
    payload = {
        "source": "aws.some-other-service",
        "detail-type": "Something Happened",
        "detail": {},
    }
    event = parse_pipeline_event(payload)
    assert event["event_type"] == "unknown"
    assert event["source"] == "aws.some-other-service"
    assert event["run_id"] is None


def test_parse_event_accepts_python_style_sqs_body():
    """Some producers deliver a single-quoted dict string rather than strict JSON."""
    message = {
        "MessageId": "single-quote-body-001",
        "Body": "{'MessageId': 'single-quote-body-001', 'source': 'aws.states', 'detail-type': 'Step Functions Execution Status Change', 'time': '2026-10-07T05:00:00Z', 'detail': {'executionArn': 'arn:aws:states:ap-south-1:449902674528:execution:pdf-ingestion-pipeline:run-quoted', 'status': 'SUCCEEDED'}}",
    }

    event = __import__("server.pipeline.events", fromlist=["parse_event"]).parse_event(message)

    assert event["event_id"] == "single-quote-body-001"
    assert event["run_id"] == "run-quoted"
    assert event["event_type"] == "sfn.state_change"
    assert event["status"] == "SUCCEEDED"


def test_parse_event_accepts_unquoted_dict_sqs_body():
    """Malformed producer payloads sometimes omit JSON quotes around keys and values."""
    message = {
        "MessageId": "test-sfn-success-001",
        "Body": "{MessageId:test-sfn-success-001,source:aws.states,detail-type:Step Functions Execution Status Change,time:2026-10-07T08:45:00Z,detail:{executionArn:arn:aws:states:ap-south-1:449902674528:execution:pdf-ingestion-pipeline:manual-test-001,stateMachineArn:arn:aws:states:ap-south-1:449902674528:stateMachine:pdf-ingestion-pipeline,status:SUCCEEDED}}",
    }

    event = __import__("server.pipeline.events", fromlist=["parse_event"]).parse_event(message)

    assert event["event_id"] == "test-sfn-success-001"
    assert event["run_id"] == "manual-test-001"
    assert event["event_type"] == "sfn.state_change"
    assert event["status"] == "SUCCEEDED"


def test_consumer_drops_poison_message_after_three_attempts():
    from server.pipeline.consumer import _handle_failed_message

    sent = {"send": 0, "delete": 0}

    class FakeSQS:
        def send_message(self, **kwargs):
            sent["send"] += 1
            return {"MessageId": "dlq-message-1"}

        def delete_message(self, **kwargs):
            sent["delete"] += 1
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    message = {
        "MessageId": "poison-1",
        "Body": "{bad payload}",
        "Attributes": {"ApproximateReceiveCount": "3"},
        "ReceiptHandle": "abc123",
    }

    _handle_failed_message(FakeSQS(), message, ValueError("bad payload"))

    assert sent["send"] == 0
    assert sent["delete"] == 1


def test_parse_event_accepts_nested_ecs_task_state_change_payload():
    payload = {
        "version": "0",
        "id": "5b3c7c48-8ec8-1b52-d147-9d524cc989ab",
        "detail-type": "ECS Task State Change",
        "source": "aws.ecs",
        "account": "449902674528",
        "time": "2026-10-07T08:32:55Z",
        "region": "ap-south-1",
        "detail": {
            "clusterArn": "arn:aws:ecs:ap-south-1:449902674528:cluster/medicine-scanner-cluster",
            "taskArn": "arn:aws:ecs:ap-south-1:449902674528:task/medicine-scanner-cluster/0ac6a99cc0a74871aa435d41b78f0a0d",
            "lastStatus": "STOPPED",
            "stoppedReason": "Essential container in task exited",
            "containers": [{
                "containerArn": "arn:aws:ecs:ap-south-1:449902674528:container/benchmark/8a8d5408bb2a4bf49d6e4bd1d1f5f91d",
                "taskArn": "arn:aws:ecs:ap-south-1:449902674528:task/medicine-scanner-cluster/0ac6a99cc0a74871aa435d41b78f0a0d",
                "name": "data-processor",
                "image": "123456789012.dkr.ecr.ap-south-1.amazonaws.com/data-processor:latest",
                "lastStatus": "STOPPED",
                "exitCode": 1,
                "networkInterfaces": [{
                    "attachmentId": "abc123",
                    "privateIpv4Address": "10.0.0.5",
                }],
                "networkBindings": [],
            }],
            "createdAt": "2026-10-07T08:32:00Z",
            "startedAt": "2026-10-07T08:32:20Z",
            "stoppedAt": "2026-10-07T08:32:55Z",
            "overrides": {
                "containerOverrides": [{
                    "name": "data-ingester",
                    "command": [
                        "python",
                        "data_processing_service/main.py",
                        "--run-id",
                        "ecs-run-123",
                        "--manifest-s3-key",
                        "medicine-data-storage/processed_files/runs/ecs-run-123/manifest.json",
                    ],
                }]
            },
            "attachments": [{
                "id": "abc",
                "type": "ElasticNetworkInterface",
                "status": "DELETED",
                "details": [{
                    "name": "subnetId",
                    "value": "subnet-123",
                }, {
                    "name": "networkInterfaceId",
                    "value": "eni-123",
                }],
            }],
        },
    }

    parsed = __import__("server.pipeline.events", fromlist=["parse_event"]).parse_event({"MessageId": "ecs-msg-123", "Body": json.dumps(payload)})

    assert parsed["event_id"] == "ecs-msg-123"
    assert parsed["event_type"] == "ecs.task_state_change"
    assert parsed["source"] == "aws.ecs"
    assert parsed["run_id"] == "ecs-run-123"
    assert parsed["status"] is None
    assert parsed["payload"]["detail"]["containers"][0]["networkInterfaces"][0]["privateIpv4Address"] == "10.0.0.5"


def test_sfn_success_populates_manifest_key_for_pending_approval(monkeypatch):
    from server.database.models import RunApproval
    from server.pipeline import consumer
    from server.pipeline.routes import list_runs

    class FakeQuery:
        def __init__(self, rows):
            self.rows = list(rows)

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return list(self.rows)

    class FakeSession:
        def __init__(self):
            self.rows = {}

        def query(self, model):
            return FakeQuery(self.rows.get(model, []))

        def add(self, obj):
            self.rows.setdefault(type(obj), []).append(obj)

        def commit(self):
            pass

        def close(self):
            pass

    fake_session = FakeSession()
    monkeypatch.setattr(consumer, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(consumer.boto3, "client", lambda *args, **kwargs: type("FakeS3", (), {"head_object": lambda self, **kw: (_ for _ in ()).throw(ClientError({"Error": {"Code": "404", "Message": "Missing"}}, "HeadObject"))})())

    event = {
        "event_id": "sfn-success-456",
        "event_type": "sfn.state_change",
        "source": "aws.states",
        "run_id": "manual-test-001",
        "status": "SUCCEEDED",
        "payload": {
            "detail": {
                "executionArn": "arn:aws:states:ap-south-1:449902674528:execution:pdf-ingestion-pipeline:manual-test-001",
                "status": "SUCCEEDED",
            }
        },
    }

    assert consumer._persist_event(event) is True
    runs = list_runs(db=fake_session)

    assert any(run["run_id"] == "manual-test-001" and run["manifest_key"] == "medicine-data-storage/processed_files/runs/manual-test-001/manifest.json" for run in runs)


def test_approve_run_uses_container_args_only(monkeypatch):
    import asyncio

    from server.database.models import RunApproval
    from server.pipeline import approval_service

    class FakeQuery:
        def __init__(self, row):
            self.row = row

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.row

    class FakeDB:
        def __init__(self, row):
            self.row = row

        def query(self, model):
            return FakeQuery(self.row)

        def commit(self):
            pass

    approval = RunApproval(
        run_id="run-approve-1",
        status="pending",
        manifest_key="medicine-data-storage/processed_files/runs/run-approve-1/manifest.json",
    )
    fake_db = FakeDB(approval)

    class FakeECS:
        def __init__(self):
            self.calls = []

        def run_task(self, **kwargs):
            self.calls.append(kwargs)
            return {"tasks": [{"taskArn": "arn:aws:ecs:ap-south-1:123:task/test-task"}]}

    fake_ecs = FakeECS()
    monkeypatch.setattr(approval_service, "S3_BUCKET_NAME", "medicine-data-storage-449902674528-ap-south-1-an")
    monkeypatch.setattr(approval_service, "AWS_REGION", "ap-south-1")
    monkeypatch.setattr(approval_service.boto3, "client", lambda *args, **kwargs: fake_ecs)

    result = asyncio.run(approval_service.approve_run("run-approve-1", "admin", fake_db))

    assert result["status"] == "approved"
    command = fake_ecs.calls[0]["overrides"]["containerOverrides"][0]["command"]
    assert command == [
        "--bucket",
        "medicine-data-storage-449902674528-ap-south-1-an",
        "--region",
        "ap-south-1",
        "--manifest-s3-key",
        "medicine-data-storage/processed_files/runs/run-approve-1/manifest.json",
        "--run-id",
        "run-approve-1",
        "--commit",
    ]
    assert "python" not in command
    assert "-m" not in command


def test_resolve_manifest_key_requires_existing_s3_object(monkeypatch):
    from server.pipeline import consumer

    calls = []

    class FakeS3:
        def head_object(self, **kwargs):
            calls.append(kwargs)
            if kwargs["Key"] == "medicine-data-storage/processed_files/runs/run-verified/manifest.json":
                return {"ResponseMetadata": {"HTTPStatusCode": 200}}
            raise ClientError({"Error": {"Code": "404", "Message": "Missing"}}, "HeadObject")

    monkeypatch.setattr(consumer, "S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(consumer, "S3_PREFIX", "medicine-data-storage")
    monkeypatch.setattr(consumer.boto3, "client", lambda *args, **kwargs: FakeS3())

    assert consumer._resolve_manifest_key("run-verified", {"detail": {}}) == "medicine-data-storage/processed_files/runs/run-verified/manifest.json"
    assert consumer._resolve_manifest_key("run-missing", {"detail": {}}) == "medicine-data-storage/processed_files/runs/run-missing/manifest.json"