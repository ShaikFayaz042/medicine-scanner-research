from sqlalchemy import BigInteger, MetaData, create_engine, insert, inspect
from sqlalchemy.orm import Session

from server.database import models
from server.database.init_db import ensure_pipeline_tables


def test_ensure_pipeline_tables_migrates_sqlite_bigint_ids_without_losing_rows():
    engine = create_engine("sqlite://")
    legacy_metadata = MetaData()
    legacy_tables = []

    for model in (models.PipelineEvent, models.RunApproval):
        legacy_table = model.__table__.to_metadata(legacy_metadata)
        legacy_table.c.id.type = BigInteger()
        legacy_tables.append(legacy_table)

    legacy_metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(legacy_tables[0]).values(
                id=7,
                event_id="existing-event",
                event_type="ecs.task_state_change",
                source="aws.ecs",
                payload={"existing": True},
            )
        )
        connection.execute(
            insert(legacy_tables[1]).values(
                id=11,
                run_id="existing-run",
                status="pending",
            )
        )

    ensure_pipeline_tables(engine)

    inspector = inspect(engine)
    for table_name in ("pipeline_events", "run_approvals"):
        id_column = next(
            column for column in inspector.get_columns(table_name) if column["name"] == "id"
        )
        assert str(id_column["type"]).upper() == "INTEGER"

    with Session(engine) as session:
        event = session.query(models.PipelineEvent).filter_by(event_id="existing-event").one()
        approval = session.query(models.RunApproval).filter_by(run_id="existing-run").one()
        assert event.id == 7
        assert event.payload == {"existing": True}
        assert approval.id == 11

        session.add(
            models.PipelineEvent(
                event_id="new-event",
                event_type="ecs.task_state_change",
                source="aws.ecs",
                payload={},
            )
        )
        session.add(models.RunApproval(run_id="new-run", status="pending"))
        session.commit()

        new_event = session.query(models.PipelineEvent).filter_by(event_id="new-event").one()
        new_approval = session.query(models.RunApproval).filter_by(run_id="new-run").one()
        assert new_event.id == 8
        assert new_approval.id == 12
