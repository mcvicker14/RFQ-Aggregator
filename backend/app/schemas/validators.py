"""Shared field types. Frontend date/time inputs (e.g. HTML datetime-local) commonly
arrive with no UTC offset; treating them as naive would later crash any comparison
against an aware `datetime.now(timezone.utc)` (dashboard KPIs, scoring timing). Every
Opportunity datetime field uses AwareDatetime so this is normalized once, at the API
boundary, instead of defensively re-checked in every service function.
"""
from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]
