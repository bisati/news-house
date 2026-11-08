"""Profile loading with versioning."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.config import Settings
from newshouse.models import Profile


def load_profile(session: Session, settings: Settings) -> Profile:
    path = settings.profile_path
    if not path.is_file():
        raise FileNotFoundError(f"profile file not found: {path}")
    text = path.read_text()
    last = session.scalars(
        select(Profile).where(Profile.profile_id == settings.profile_id)
        .order_by(Profile.version.desc()).limit(1)
    ).first()
    if last is not None and last.text == text:
        return last
    row = Profile(id=uuid4().hex, profile_id=settings.profile_id,
                  version=(last.version + 1) if last else 1, text=text)
    session.add(row)
    session.flush()
    return row
