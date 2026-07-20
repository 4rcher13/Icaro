"""
Tests para validar la implementación del sistema de memoria compartida.

Verifica que:
1. El singleton de shared_memory se inicializa correctamente
2. Los eventos de MCPs se registran en la memoria compartida
3. Los eventos de ActionService se registran correctamente
4. El acceso a memoria es thread-safe
"""
import time
import threading
import pytest
from pathlib import Path

from src.core.memory_manager import MemoryManager
from src.core.shared_memory import (
    set_shared_memory, 
    get_shared_memory, 
    log_event
)
from src.mcps.sequential_thinking import SequentialThinkingMCP
from src.mcps.obsidian_mcp import ObsidianMCP
from src.mcps.github_mcp import GitHubMCP
from src.mcps.cybersecurity_mcp import CybersecurityMCP
from src.mcps.gemini_mcp import GeminiMCP


class TestSharedMemorySingleton:
    """Tests para el patrón singleton de shared_memory."""
    
    def test_set_and_get_shared_memory(self):
        """Verifica que se puede registrar y recuperar la instancia compartida."""
        memory = MemoryManager()
        set_shared_memory(memory)
        
        retrieved = get_shared_memory()
        assert retrieved is memory
        assert retrieved is not None
    
    def test_get_shared_memory_before_set(self):
        """Verifica que get devuelve None si aún no se ha registrado."""
        # Resetear el singleton
        import src.core.shared_memory as sm_module
        original_instance = sm_module._shared_memory_instance
        sm_module._shared_memory_instance = None
        
        try:
            result = get_shared_memory()
            assert result is None
        finally:
            # Restaurar
            sm_module._shared_memory_instance = original_instance


class TestMemoryManagerGuardarEvento:
    """Tests para el método guardar_evento de MemoryManager."""
    
    def test_guardar_evento_basico(self):
        """Verifica que se guarda un evento en el historial."""
        memory = MemoryManager()
        memory.guardar_evento("TestMCP", "test_event", "Test content")
        
        # Permitir tiempo para que se guarde
        time.sleep(0.1)
        
        history = memory.cargar()
        assert len(history) > 0
        
        last_item = history[-1]
        assert last_item["role"] == "system"
        assert last_item.get("source") == "TestMCP"
        assert last_item.get("event_type") == "test_event"
        assert "Test content" in last_item["text"]
    
    def test_guardar_evento_redaccion(self):
        """Verifica que los eventos sensibles se redactan."""
        memory = MemoryManager()
        memory.guardar_evento(
            "TestMCP", 
            "sensitive", 
            "token: secret_12345 password: mypass123"
        )
        
        time.sleep(0.1)
        history = memory.cargar()
        last_item = history[-1]
        
        # Verificar que las palabras clave sensibles fueron redactadas
        assert "secret_12345" not in last_item["text"]
        assert "mypass123" not in last_item["text"]
        assert "[REDACTADO]" in last_item["text"]


class TestLogEventAsync:
    """Tests para la función log_event (no-bloqueante)."""
    
    def test_log_event_registers_in_memory(self):
        """Verifica que log_event registra eventos en la memoria compartida."""
        memory = MemoryManager()
        set_shared_memory(memory)
        
        # Hacer un log
        log_event("TestService", "test_event", "Test message")
        
        # Esperar a que se procese en el thread
        time.sleep(0.3)
        
        history = memory.cargar()
        system_msgs = [h for h in history if h.get("role") == "system"]
        assert len(system_msgs) > 0
        
        last_system = system_msgs[-1]
        assert "TestService" in last_system["text"]
        assert "Test message" in last_system["text"]
    
    def test_log_event_without_shared_memory(self):
        """Verifica que log_event no falla si shared_memory no está inicializada."""
        import src.core.shared_memory as sm_module
        original_instance = sm_module._shared_memory_instance
        sm_module._shared_memory_instance = None
        
        try:
            # No debe lanzar excepción
            log_event("TestService", "test_event", "Test message")
            time.sleep(0.1)
        finally:
            sm_module._shared_memory_instance = original_instance


class TestMCPsIntegration:
    """Tests para verificar que los MCPs registran eventos en shared_memory."""
    
    def test_sequential_thinking_records_to_memory(self):
        """Verifica que SequentialThinkingMCP registra pasos en memoria compartida."""
        memory = MemoryManager()
        set_shared_memory(memory)
        
        thinking = SequentialThinkingMCP()
        thinking.record_step("Analizar el problema", 1, 3)
        
        time.sleep(0.2)
        history = memory.cargar()
        system_msgs = [h for h in history if h.get("role") == "system"]
        
        assert len(system_msgs) > 0
        assert any("SequentialThinkingMCP" in h["text"] for h in system_msgs)
    
    def test_cybersecurity_mcp_records_cve_search(self):
        """Verifica que CybersecurityMCP registra búsquedas de CVE."""
        memory = MemoryManager()
        set_shared_memory(memory)
        
        cve_mcp = CybersecurityMCP()
        # Buscar una práctica de seguridad (no requiere API)
        cve_mcp.get_security_best_practice("sql injection")
        
        time.sleep(0.2)
        history = memory.cargar()
        system_msgs = [h for h in history if h.get("role") == "system"]
        
        assert len(system_msgs) > 0
        assert any("CybersecurityMCP" in h["text"] for h in system_msgs)


class TestConcurrentAccess:
    """Tests para verificar thread-safety de la memoria compartida."""
    
    def test_concurrent_log_events(self):
        """Verifica que múltiples threads pueden registrar eventos simultaneamente."""
        memory = MemoryManager()
        set_shared_memory(memory)
        
        results = []
        
        def log_from_thread(thread_id):
            for i in range(5):
                log_event(f"Thread{thread_id}", f"event_{i}", f"Message {i}")
            results.append(thread_id)
        
        threads = [
            threading.Thread(target=log_from_thread, args=(i,))
            for i in range(3)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        time.sleep(0.5)
        
        # Verificar que todos los threads completaron
        assert len(results) == 3
        
        # Verificar que se registraron eventos de todos
        history = memory.cargar()
        system_msgs = [h for h in history if h.get("role") == "system"]
        
        assert len(system_msgs) >= 3  # Al menos uno de cada thread


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
