"""SQLite and SQLAlchemy configuration."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "document_intelligence.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

DATA_DIR.mkdir(exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy models."""


def get_session() -> Generator[Session, None, None]:
    """Yield a database session and always close it afterward."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create all registered tables."""
    Base.metadata.create_all(bind=engine)


def database_status() -> str:
    """Return a small health status for the Streamlit sidebar."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return f"SQLite connected: {DATABASE_PATH.name}"
    except Exception:
        return "SQLite connection unavailable"
