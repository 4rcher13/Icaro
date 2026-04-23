import pytest
from pathlib import Path
from src.core.icaro import Icaro
from src.core.protocols import AudioProtocol, AIProtocol, MemoryProtocol, ActionProtocol
from src.services.action_service import ActionService
from src.core.memory_manager import MemoryManager
from src.core.command_processor import CommandProcessor

class MockAudio:
    def __init__(self):
        self.ultima_interaccion = 0
    def hablar(self, texto): pass
    def escuchar(self, **kwargs): return "abre notepad"

class MockAI:
    def route_command(self, text):
        if "notepad" in text:
            return {"intent": "abrir_aplicacion", "target": "notepad", "respuesta": "Abriendo bloc de notas"}
        return {"intent": None, "target": None, "respuesta": "No entiendo"}
    def summarize(self, text): return "Resumen"

def test_integration_flow(tmp_path):
    # Setup test environment
    history_file = tmp_path / "historial.json"
    
    # We need to manually set the history file for MemoryManager
    import src.core.memory_manager as mm
    original_file = mm.HISTORY_FILE
    mm.HISTORY_FILE = str(history_file)
    
    # Initialize services
    audio = MockAudio()
    ai = MockAI()
    memory = MemoryManager(buffer_size=1) # Flush immediately for testing
    action = ActionService()
    
    # Initialize Icaro with DI
    icaro = Icaro(
        silent=True,
        audio_service=audio,
        ai_service=ai,
        memory_manager=memory,
        action_service=action
    )
    
    # Execute a cycle
    icaro._ciclo_procesamiento("abre notepad")
    
    # Verify memory
    history = memory.cargar()
    assert len(history) >= 2
    assert history[0]["role"] == "user"
    assert "abre notepad" in history[0]["text"]
    assert history[1]["role"] == "model"
    assert "Abriendo bloc de notas" in history[1]["text"]
    
    # Cleanup
    mm.HISTORY_FILE = original_file

def test_normalization_integration():
    # Test that CommandProcessor uses the new normalization
    from src.core.command_processor import CommandProcessor
    from src.services.action_service import ActionService
    
    cp = CommandProcessor(ai_service=MockAI(), action_service=ActionService(), use_rapidfuzz=True)
    
    # "notepadd" should match "notepad" if rapidfuzz is working
    clean = cp._normalize("notepadd")
    assert clean == "notepad"
