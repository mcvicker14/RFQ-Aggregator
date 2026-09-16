"""Minimal key-value app settings. See docs/PHASE2_ARCHITECTURE.md §9 — currently
just HIDE_SAMPLE_DATA_KEY, but generic enough to reuse for any future app-wide switch
without another migration.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.intelligence import AppSetting

HIDE_SAMPLE_DATA_KEY = "hide_sample_data_by_default"


def get_setting(db: Session, key: str, default):
    setting = db.get(AppSetting, key)
    return setting.value if setting is not None else default


def set_setting(db: Session, key: str, value, updated_by_user_id: UUID | None) -> AppSetting:
    setting = db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value, updated_by_user_id=updated_by_user_id)
        db.add(setting)
    else:
        setting.value = value
        setting.updated_by_user_id = updated_by_user_id
    db.commit()
    db.refresh(setting)
    return setting


def hide_sample_data_by_default(db: Session) -> bool:
    return bool(get_setting(db, HIDE_SAMPLE_DATA_KEY, False))
