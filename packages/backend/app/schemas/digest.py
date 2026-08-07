from datetime import date as date_type
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DigestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    digest_date: date_type
    content: str
    summary_stats: dict
    created_at: datetime


class DigestGenerateRequest(BaseModel):
    date: date_type | None = Field(
        default=None, description="Date in YYYY-MM-DD format, defaults to yesterday"
    )
