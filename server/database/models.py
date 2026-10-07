"""Server SQLAlchemy models used by the FastAPI app."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, JSON, String, Text, func

from server.database.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(BigInteger, unique=True, nullable=False, index=True)
    source = Column(String, nullable=False, default="unknown", index=True)
    source_key = Column(String, nullable=True, index=True)
    document_type = Column(String, nullable=True, index=True)
    source_metadata = Column("metadata", JSON, nullable=True)
    title = Column(String, nullable=False)
    release_date = Column(String, nullable=False)
    pdf_url = Column(String, nullable=False)
    pdf_size_declared = Column(String, nullable=True)
    local_file_path = Column(String, nullable=True)
    s3_object_key = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    content_hash = Column(String, nullable=True)
    status = Column(String, nullable=False, default="discovered")
    profile_status = Column(String, nullable=True)
    processing_stage = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    source = Column(String(32), nullable=False)
    run_id = Column(String(64), nullable=True, index=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=False)


class RunApproval(Base):
    __tablename__ = "run_approvals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(16), nullable=False, index=True)
    manifest_key = Column(Text, nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(String(128), nullable=True)
    ingester_task_arn = Column(Text, nullable=True)
    ingester_completed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)


class SchedulerConfig(Base):
    """Legacy model retained for import compatibility; not initialized here."""

    __tablename__ = "scheduler_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hour = Column(Integer, nullable=False, default=2)
    minute = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    day_of_month = Column(Integer, nullable=True)
    month = Column(Integer, nullable=True)
    day_of_week = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_documents_status", Document.status)
Index("ix_documents_release_date", Document.release_date)

__all__ = ["Document", "PipelineEvent", "RunApproval", "SchedulerConfig"]
