"""Pydantic schemas"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskCreateResponse(BaseModel):
    id: uuid.UUID
    md5: str
    original_name: str
    status: str
    raw_minio_path: str
    message: str


class TaskStatusResponse(BaseModel):
    id: uuid.UUID
    md5: str
    original_name: str
    status: str
    parsed_minio_path: str | None = None
    error_msg: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
