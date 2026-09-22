"""SQLAlchemy models."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String

from automated_scraper_demo.database.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(BigInteger, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    release_date = Column(String, nullable=False)
    pdf_url = Column(String, nullable=False)
    pdf_size_declared = Column(String, nullable=True)
    local_file_path = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    content_hash = Column(String, nullable=True)
    status = Column(String, nullable=False, default="discovered")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SchedulerConfig(Base):
    __tablename__ = "scheduler_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hour = Column(Integer, nullable=False, default=2)
    minute = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_documents_status", Document.status)
Index("ix_documents_release_date", Document.release_date)
