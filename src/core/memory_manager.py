import os
import json
import logging
from pathlib import Path

from ..config.settings import HISTORY_FILE, MAX_HISTORY

logger = logging.getLogger(__name__)

class MemoryManager:
    """Maneja la persistencia del historial de conversación de Ícaro."""

    def __init__(self):
        self.archivo = Path(HISTORY_FILE)
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.max_items = MAX_HISTORY
        self.historial = self._leer_archivo()

    def _leer_archivo(self):
        """Lee el historial del disco de forma segura en la inicialización."""
        try:
            if not self.archivo.exists():
                return []
            with open(self.archivo, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Historial corrupto, reiniciando")
            return []
        except OSError:
            logger.error("Error de I/O leyendo historial.")
            return []

    def cargar(self):
        """Devuelve la caché del historial en memoria."""
        return self.historial

    def guardar(self, rol: str, texto: str):
        """Guarda un nuevo mensaje en el historial controlando el límite de tamaño."""
        # Comprimir comandos muy largos para no desbordar memoria
        texto_guardar = f"[Código omitido: {texto[:50]}...]" if len(texto) > 1000 else texto
        
        self.historial.append({"role": "user" if rol == "user" else "model", "text": texto_guardar})
        
        # Recorte de listado para límite de ítems
        if len(self.historial) > self.max_items:
            self.historial = self.historial[-self.max_items:]

        try:
            temp = self.archivo.with_suffix(".tmp")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self.historial, f, ensure_ascii=False, indent=2)
            temp.replace(self.archivo)
        except Exception as e:
            logger.error(f"Error guardando historial de forma atómica: {e}")
