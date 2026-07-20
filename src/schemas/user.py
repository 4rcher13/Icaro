"""Esquemas de validación para usuarios"""

from pydantic import EmailStr, Field, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime
from .base import BaseSchema

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"

class UserCreate(BaseSchema):
    """Validación para crear usuario"""
    email: EmailStr = Field(..., description="Email único del usuario")
    password: str = Field(..., min_length=8, max_length=128, description="Contraseña (mín 8 caracteres)")
    full_name: str = Field(..., min_length=1, max_length=255, description="Nombre completo")
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Valida fortaleza de contraseña"""
        if not any(c.isupper() for c in v):
            raise ValueError('Debe contener al menos una mayúscula')
        if not any(c.isdigit() for c in v):
            raise ValueError('Debe contener al menos un número')
        if not any(c in '!@#$%^&*' for c in v):
            raise ValueError(r'Debe contener al menos un carácter especial (!@#\$%^&*)')
        return v

class UserUpdate(BaseSchema):
    """Validación para actualizar usuario"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None

class UserResponse(BaseSchema):
    """Response de usuario (sin exponer contraseña)"""
    id: int
    email: str
    full_name: str
    role: UserRole
    created_at: datetime
    
    model_config = {
    "from_attributes": True
}
