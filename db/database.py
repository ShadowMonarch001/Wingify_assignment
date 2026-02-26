## ─────────────────────────────────────────────────────────────────────────────
## db/database.py  —  SQLAlchemy engine, session factory, and Base
## ─────────────────────────────────────────────────────────────────────────────
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Read DATABASE_URL from environment (set in .env)
# Format: postgresql://user:password@host:port/dbname
# For SQLite (dev/testing): sqlite:///./financial_analyzer.db
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./financial_analyzer.db",  # safe fallback for local dev
)

# For SQLite, we need check_same_thread=False; ignored for PostgreSQL
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,      # verify connections before use (avoids stale connections)
    pool_recycle=3600,       # recycle connections after 1 hour
    echo=False,              # set True to log all SQL (useful for debugging)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session and ensures it is closed."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context manager for use outside FastAPI (e.g. in Celery workers)."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_tables() -> None:
    """Create all tables if they do not already exist. Called at app startup."""
    # Import models here to ensure they are registered on Base.metadata
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)