"""SQLAlchemy 2.x ORM models.

Mirrors the data model from PLAN.md §3. M0 only needs the tables to exist
with sensible columns; later milestones will fill in indexes, constraints
and helper methods.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lemma: Mapped[str] = mapped_column(String(128), index=True)
    article: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pos: Mapped[str] = mapped_column(String(16), index=True)
    level: Mapped[str | None] = mapped_column(String(4), nullable=True, index=True)
    frequency: Mapped[int] = mapped_column(Integer, default=0, index=True)
    ipa: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plural: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    senses: Mapped[list[Sense]] = relationship(back_populates="word", cascade="all, delete-orphan")


class Sense(Base):
    __tablename__ = "senses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), index=True)
    definition_de: Mapped[str | None] = mapped_column(Text, nullable=True)
    register: Mapped[str | None] = mapped_column(String(32), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)

    word: Mapped[Word] = relationship(back_populates="senses")
    examples: Mapped[list[Example]] = relationship(
        back_populates="sense", cascade="all, delete-orphan"
    )
    dialogues: Mapped[list[Dialogue]] = relationship(
        back_populates="sense", cascade="all, delete-orphan"
    )


class Example(Base):
    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sense_id: Mapped[int] = mapped_column(ForeignKey("senses.id", ondelete="CASCADE"), index=True)
    text_de: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32))
    translation_en: Mapped[str | None] = mapped_column(Text, nullable=True)

    sense: Mapped[Sense] = relationship(back_populates="examples")


class Dialogue(Base):
    __tablename__ = "dialogues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sense_id: Mapped[int] = mapped_column(ForeignKey("senses.id", ondelete="CASCADE"), index=True)
    text_de: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    sense: Mapped[Sense] = relationship(back_populates="dialogues")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    cards: Mapped[list[ReviewCard]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ReviewCard(Base):
    __tablename__ = "review_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sense_id: Mapped[int] = mapped_column(ForeignKey("senses.id", ondelete="CASCADE"), index=True)

    stability: Mapped[float | None] = mapped_column(nullable=True)
    difficulty: Mapped[float | None] = mapped_column(nullable=True)
    due: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    last_review: Mapped[datetime | None] = mapped_column(nullable=True)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="new")

    user: Mapped[User] = relationship(back_populates="cards")
    logs: Mapped[list[ReviewLog]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("review_cards.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    rating: Mapped[int] = mapped_column(Integer)
    elapsed_days: Mapped[float | None] = mapped_column(nullable=True)
    scheduled_days: Mapped[float | None] = mapped_column(nullable=True)

    card: Mapped[ReviewCard] = relationship(back_populates="logs")
