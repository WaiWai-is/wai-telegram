from datetime import date as date_type, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DigestResponse(BaseModel):
    id: UUID
    digest_date: date_type
    content: str
    summary_stats: dict
    created_at: datetime

    class Config:
        from_attributes = True


class DigestGenerateRequest(BaseModel):
    date: date_type | None = Field(default=None, description="Date in YYYY-MM-DD format, defaults to yesterday")
