"""Read-only database runtime for normalized medicine data."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.config import MEDICINE_DATABASE_URL


medicine_engine = create_engine(MEDICINE_DATABASE_URL, echo=False, future=True)
MedicineSessionLocal = sessionmaker(bind=medicine_engine, autoflush=False, autocommit=False)


__all__ = ["MedicineSessionLocal", "medicine_engine"]