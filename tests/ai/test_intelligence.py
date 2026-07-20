import sys
import os
from unittest.mock import MagicMock

# Añadir src al path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.memory_manager import MemoryManager
from src.services.ai_service import AIService

def test_intelligence():
    print("--- Probando Inteligencia de Ícaro ---")
    
    # 1. Setup
    memory = MemoryManager()
    # Limpiar historial para el test
    memory.historial = []
    
    ai = AIService(memory)
    # Mockear el cliente Gemini para no hacer llamadas reales si no hay API KEY, 
    # o simplemente dejar que intente si la hay.
    # Para este test, asumiremos que queremos ver el PROMPT generado o la lógica de integración.
    
    # 2. Probar get_recent
    print("\n1. Probando MemoryManager.get_recent...")
    memory.guardar("user", "Hola, me llamo Jesús")
    memory.guardar("model", "Mucho gusto, Jesús. ¿Cómo te ayudo?")
    
    recent = memory.get_recent(2)
    assert len(recent) == 2
    assert recent[0]["text"] == "Hola, me llamo Jesús"
    print("[OK] MemoryManager.get_recent funciona.")

    # 3. Probar AIService con contexto (Simulado)
    print("\n2. Probando AIService context integration...")
    # Forzamos inicialización de IA (si hay API Key)
    ai._ensure_models_initialized()
    
    if not ai.ia_habilitada and not ai.ollama_habilitado:
        print("! IA no habilitada (sin API Key u Ollama). Probando solo lógica de construcción.")
    
    # Probamos la construcción del prompt internamente o el flujo
    # (En un test real mockearíamos _call_llm para ver qué recibe)
    
    print("\n3. Verificando manejo de conversación vs comandos...")
    # Simulamos respuesta de LLM para un comando
    mock_llm_cmd = {"intent": "abrir_aplicacion", "target": "notepad", "respuesta": "Abriendo bloc de notas."}
    parsed_cmd = ai._parse_routing_data(mock_llm_cmd)
    assert parsed_cmd["intent"] == "abrir_aplicacion"
    print(f"[OK] Comando detectado: {parsed_cmd['respuesta']}")

    # Simulamos respuesta de LLM para conversación
    mock_llm_conv = {"intent": None, "target": None, "respuesta": "¡Claro Jesús! Me siento genial hoy. ¿Tú cómo estás?"}
    parsed_conv = ai._parse_routing_data(mock_llm_conv)
    assert parsed_conv["intent"] is None
    assert "Jesús" in parsed_conv["respuesta"]
    print(f"[OK] Conversación detectada: {parsed_conv['respuesta']}")

    print("\n--- Test finalizado con éxito ---")

if __name__ == "__main__":
    test_intelligence()
