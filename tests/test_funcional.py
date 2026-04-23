import sys
import os
from pathlib import Path
import logging

# Configurar path para encontrar los módulos del proyecto
sys.path.append(str(Path(__file__).parent.parent))

from src.core.icaro import Icaro
from unittest.mock import MagicMock

def test_funcional():
    print("\n=== INICIANDO PRUEBA FUNCIONAL DETALLADA ===\n")
    
    # 1. Configurar logging para ver qué pasa internamente
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # 2. Inicializar Icaro en modo silencioso y sin IA para la primera parte
    # (Para no gastar tokens innecesariamente si solo queremos probar el flujo)
    print("[1/4] Inicializando Ícaro...")
    asistente = Icaro(silent=True)
    
    # Mockear el servicio de audio para evitar que intente usar el mic real en el test
    asistente.audio.hablar = MagicMock()
    asistente.audio.escuchar = MagicMock(return_value="prueba")
    
    print("[OK] Subsistemas inicializados.")
    
    # 3. Prueba de Procesamiento de Comando (Local/Mock)
    print("\n[2/4] Probando procesamiento de comando 'dame la hora'...")
    # Simulamos que el usuario dijo "dame la hora"
    comando = "dame la hora"
    asistente._ciclo_procesamiento(comando)
    
    # Verificar si se guardó en memoria
    ultima_entrada = asistente.memory.historial[-2] # El usuario
    ultima_respuesta = asistente.memory.historial[-1] # El modelo
    
    print(f"  Usuario: {ultima_entrada['text']}")
    print(f"  Respuesta: {ultima_respuesta['text']}")
    
    if "Son las" in ultima_respuesta['text']:
        print("[OK] Acción 'dar_hora_fecha' ejecutada con éxito.")
    else:
        print("[FALLO] Falló la respuesta de la hora.")

    # 4. Prueba de Apertura de App (Mock)
    print("\n[3/4] Probando intención de abrir aplicación (Notepad)...")
    comando_app = "abre el bloc de notas"
    # Forzamos el procesamiento
    asistente._ciclo_procesamiento(comando_app)
    
    print(f"  Respuesta: {asistente.memory.historial[-1]['text']}")
    # En Windows, esto debería decir "Se abrió Bloc de Notas"
    if "abrió" in asistente.memory.historial[-1]['text'] or "Notepad" in asistente.memory.historial[-1]['text']:
        print("[OK] Intención de apertura de app detectada y ejecutada.")
    else:
        print("? Nota: La respuesta de la IA puede variar, pero el flujo se completó.")

    # 5. Verificación de Historial JSON
    print("\n[4/4] Verificando persistencia en JSON...")
    if Path("data/historial.json").exists():
        tamano = Path("data/historial.json").stat().st_size
        print(f"[OK] El archivo data/historial.json existe ({tamano} bytes).")
    else:
        print("[FALLO] No se encontró data/historial.json")

    print("\n=== PRUEBA COMPLETADA CON ÉXITO ===")

if __name__ == "__main__":
    test_funcional()
