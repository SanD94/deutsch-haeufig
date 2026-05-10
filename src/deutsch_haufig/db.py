"""SQLAlchemy engine + session bootstrap."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from deutsch_haufig.config import settings
from deutsch_haufig.models import Base

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create all tables defined on `Base.metadata` if they don't exist."""
    Base.metadata.create_all(engine)
    _apply_migrations(engine)


def _apply_migrations(engine) -> None:
    """Add columns that were added after initial table creation."""
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("review_cards")}
    if "created_at" not in existing_cols:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE review_cards "
                    "ADD COLUMN created_at TIMESTAMP"
                )
            )


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped Session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
