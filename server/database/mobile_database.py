"""Dedicated mobile session runtime on the shared medicine Supabase database."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.config import MOBILE_DATABASE_URL

mobile_engine = create_engine(MOBILE_DATABASE_URL, echo=False, future=True, pool_pre_ping=True)
MobileSessionLocal = sessionmaker(bind=mobile_engine, autoflush=False, autocommit=False)


def get_mobile_db():
    """Yield a per-request connection for the dedicated mobile schema."""
    db = MobileSessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["MobileSessionLocal", "get_mobile_db", "mobile_engine"]
