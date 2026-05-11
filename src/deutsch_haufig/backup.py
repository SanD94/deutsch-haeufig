"""Backup — export all user data to JSON (M6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from deutsch_haufig.config import settings
from deutsch_haufig.db import SessionLocal, init_db
from deutsch_haufig.models import ReviewCard, ReviewLog, User


def export_backup() -> dict:
    """Export all user data as a JSON-serialisable dict."""
    init_db()
    backup: dict = {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": "0.1.0",
        "users": [],
    }
    with SessionLocal() as session:
        users = session.execute(select(User)).scalars().all()
        for user in users:
            cards = (
                session.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
                .scalars()
                .all()
            )

            user_data = {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "settings": json.loads(user.settings_json) if user.settings_json else {},
                "cards": [],
            }

            for card in cards:
                logs = (
                    session.execute(
                        select(ReviewLog).where(ReviewLog.card_id == card.id).order_by(ReviewLog.ts)
                    )
                    .scalars()
                    .all()
                )

                user_data["cards"].append(
                    {
                        "id": card.id,
                        "sense_id": card.sense_id,
                        "stability": card.stability,
                        "difficulty": card.difficulty,
                        "due": card.due.isoformat() if card.due else None,
                        "last_review": card.last_review.isoformat() if card.last_review else None,
                        "reps": card.reps,
                        "lapses": card.lapses,
                        "state": card.state,
                        "logs": [
                            {
                                "ts": log.ts.isoformat() if log.ts else None,
                                "rating": log.rating,
                                "elapsed_days": log.elapsed_days,
                                "scheduled_days": log.scheduled_days,
                            }
                            for log in logs
                        ],
                    }
                )

            backup["users"].append(user_data)

    return backup


def run_backup(output: str | None = None) -> str:
    """Run a backup and write to *output* (or ``data/backup/`` with timestamp)."""
    data = export_backup()
    if output is None:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_dir = settings.data_dir / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        output = str(backup_dir / f"backup_{ts}.json")

    Path(output).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(
        f"Backup written to {output}  ({len(data['users'])} users, "
        f"{sum(len(u['cards']) for u in data['users'])} cards)"
    )
    return output


def main() -> None:
    """CLI entry: ``uv run backup``."""
    import argparse

    parser = argparse.ArgumentParser(description="Export user data to JSON")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()
    run_backup(args.output)


if __name__ == "__main__":
    main()
