"""Pydantic schemas for authentication requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr


class EmailRequest(BaseModel):
    email: EmailStr


class RegistrationOptionsResponse(BaseModel):
    options: dict[str, Any]


class RegisterCompleteRequest(BaseModel):
    email: EmailStr
    credential: dict[str, Any]


class LoginCompleteRequest(BaseModel):
    email: EmailStr
    credential: dict[str, Any]


class UserResponse(BaseModel):
    id: int
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}
