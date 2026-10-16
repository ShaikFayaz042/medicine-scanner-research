"""Mobile app persistence models for auth and scan history only."""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, MetaData, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

from server.config import MOBILE_DB_SCHEMA

MOBILE_SCHEMA = MOBILE_DB_SCHEMA
mobile_metadata = MetaData(schema=MOBILE_SCHEMA)
MobileBase = declarative_base(metadata=mobile_metadata)


class User(MobileBase):
    __tablename__ = "users"
    __table_args__ = {"schema": MOBILE_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(320), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ScanMethod(str, Enum):
    BARCODE = "barcode"
    BARCODE_CORRECTED = "barcode_corrected"
    OCR = "ocr"
    OCR_CORRECTED = "ocr_corrected"
    MANUAL = "manual"


class VerificationStatus(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class Scan(MobileBase):
    __tablename__ = "scans"
    __table_args__ = (
        Index(f"ix_{MOBILE_SCHEMA}_scans_user_created", "user_id", "created_at"),
        {"schema": MOBILE_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{MOBILE_SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    medicine_name = Column(String(255), default="", nullable=False)
    salt = Column(String(255), default="", nullable=False)
    batch_number = Column(String(64), default="", nullable=False)
    mfd_date = Column(String(32), default="", nullable=False)
    exp_date = Column(String(32), default="", nullable=False)
    dose = Column(String(64), default="", nullable=False)
    gtin = Column(String(14), default="", nullable=False)
    serial = Column(String(64), default="", nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    raw_input = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


__all__ = [
    "MOBILE_SCHEMA",
    "MobileBase",
    "Scan",
    "ScanMethod",
    "User",
    "VerificationStatus",
]
