"""Cloud SQLAlchemy engine, session factory, and Base for the worker."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from cloud_worker.config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Yield a DB session per request for worker-style access."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
