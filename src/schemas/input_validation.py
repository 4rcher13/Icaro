"""Validación de entrada de usuario general"""

from pydantic import Field, field_validator
from typing import Optional, List
from .base import BaseSchema

class QueryInput(BaseSchema):
    """Validación para búsquedas"""
    query: str = Field(..., min_length=1, max_length=1000, description="Término de búsqueda")
    filters: Optional[dict] = Field(default_factory=dict, description="Filtros opcionales")
    limit: int = Field(default=10, ge=1, le=100, description="Límite de resultados")
    offset: int = Field(default=0, ge=0, description="Offset para paginación")
    
    @field_validator('query')
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Sanitiza entrada de usuario"""
        dangerous_patterns = ['<', '>', '"', "'", ';', '--', '/*', '*/', 'DROP', 'DELETE', 'INSERT']
        v_upper = v.upper()
        for pattern in dangerous_patterns:
            if pattern in v_upper:
                raise ValueError(f'Patrón no permitido detectado: {pattern}')
        return v.strip()

class CommandInput(BaseSchema):
    """Validación para comandos"""
    command: str = Field(..., min_length=1, max_length=500, description="Comando a ejecutar")
    args: Optional[List[str]] = Field(default_factory=list, description="Argumentos del comando")
    
    @field_validator('command')
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Valida comando"""
        forbidden = ['rm', 'del', 'format', 'fdisk', 'dd', '>', '|', ';']
        for cmd in forbidden:
            if cmd in v.lower():
                raise ValueError(f'Comando prohibido: {cmd}')
        return v.strip()

class APIRequest(BaseSchema):
    """Validación para requests de API"""
    endpoint: str = Field(..., min_length=1, max_length=500)
    method: str = Field(default="GET", pattern="^(GET|POST|PUT|DELETE|PATCH)$")
    headers: Optional[dict] = Field(default_factory=dict)
    body: Optional[dict] = None
    
    @field_validator('endpoint')
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        """Valida endpoint"""
        if not v.startswith('/'):
            v = '/' + v
        if '..' in v or '~' in v:
            raise ValueError('Path traversal detectado')
        return v
