"""SQLAlchemy models."""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, BigInteger, Boolean, Index
)

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Government-provided internal ID (decoded from num_id base64).
    # Unique index — this is our dedup key.
    document_id = Column(BigInteger, unique=True, nullable=False, index=True)

    title = Column(String, nullable=False)
    release_date = Column(String, nullable=False)     # keep as string "2025-Oct-08"
    pdf_url = Column(String, nullable=False)
    pdf_size_declared = Column(String, nullable=True)  # e.g. "1450 KB"

    local_file_path = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    content_hash = Column(String, nullable=True)      # sha256 of downloaded file

    status = Column(String, nullable=False, default="discovered")
    # discovered -> downloaded -> processed
    # or -> failed

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class SchedulerConfig(Base):
    __tablename__ = "scheduler_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hour = Column(Integer, nullable=False, default=2)   # 2 AM default
    minute = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)

    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


Index("ix_documents_status", Document.status)
Index("ix_documents_release_date", Document.release_date)