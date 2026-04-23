import pytest
import os
import json
import re
from pathlib import Path
from src.services.action_service import ActionService
from src.core.memory_manager import MemoryManager

@pytest.fixture
def action_service():
    return ActionService()

@pytest.fixture
def memory_manager(tmp_path):
    # Mocking settings for HISTORY_FILE
    history_file = tmp_path / "test_historial.json"
    
    # We need to ensure MemoryManager uses this test file
    import src.core.memory_manager as mm
    # We can't easily patch the class attribute if it's imported as a constant
    # But we can pass it or use a test-specific instance
    
    manager = MemoryManager()
    manager.archivo = Path(history_file)
    return manager

def test_action_service_whitelist(action_service):
    # Test an allowed app
    res = action_service._abrir_aplicacion("notepad")
    # Whitelist check should pass, even if execution fails (e.g. not on Windows)
    assert "Acceso denegado" not in res
    
    # Test a forbidden app/command injection
    res = action_service._abrir_aplicacion("notepad && dir")
    assert "Acceso denegado" in res

def test_action_service_path_traversal(action_service):
    # Test creating folder with path traversal
    res = action_service._crear_carpeta("../../forbidden")
    assert "forbidden" in res
    assert ".." not in res

def test_memory_manager_redaction(memory_manager):
    # Test password redaction
    memory_manager.guardar("user", "password=mi_super_clave")
    
    history = memory_manager.cargar()
    assert "[REDACTADO]" in history[-1]["text"]
    assert "mi_super_clave" not in history[-1]["text"]

def test_memory_manager_email_redaction(memory_manager):
    memory_manager.guardar("user", "Escríbeme a test@example.com")
    history = memory_manager.cargar()
    assert "[EMAIL-REDACTADO]" in history[-1]["text"]
    assert "test@example.com" not in history[-1]["text"]

def test_memory_manager_jwt_redaction(memory_manager):
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    memory_manager.guardar("user", f"Token: {jwt}")
    history = memory_manager.cargar()
    assert "[JWT-REDACTADO]" in history[-1]["text"]
    assert jwt not in history[-1]["text"]
