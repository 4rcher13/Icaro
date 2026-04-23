import json
import logging
import re
import threading
import atexit
import time
from pathlib import Path

from ..config.settings import HISTORY_FILE, MAX_HISTORY

logger = logging.getLogger(__name__)

class MemoryManager:
    """Maneja la persistencia del historial de conversación de Ícaro."""

    def __init__(self, buffer_size: int = 5, flush_timeout: int = 30):
        self.archivo = Path(HISTORY_FILE)
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.max_items = MAX_HISTORY
        self.lock = threading.Lock()
        
        # Configuración de batching
        self.buffer_size = buffer_size
        self.flush_timeout = flush_timeout
        self.pending_changes = 0
        self.last_flush_time = time.time()
        
        self.historial = self._leer_archivo()
        
        # Registrar guardado al salir
        atexit.register(self.flush)
        
        # Hilo de limpieza periódico (opcional, pero ayuda si no hay mensajes nuevos)
        self._start_timer()

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
        with self.lock:
            return list(self.historial)

    def _redactar_sensible(self, texto: str) -> str:
        """Filtra información sensible del texto antes de persistir."""
        if not texto: 
            return texto
        
        # Patrones de seguridad críticos
        patrones = [
            # JWT (JSON Web Tokens) - Primero por ser más específico
            (r'eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+', '[JWT-REDACTADO]'),
            # Passwords, tokens, api keys en formatos comunes (evita re-redactar si ya empieza por '[')
            (r'(?i)(password|passwd|contraseña|token|api_key|secret|bearer|authorization)\s*[=:]\s*(?!\[)[^\s,;]+', r'\1: [REDACTADO]'),
            # Emails
            (r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[EMAIL-REDACTADO]'),
            # Tarjetas de crédito/débito (13-16 dígitos)
            (r'\b(?:\d[ -]*?){13,16}\b', '[TARJETA-REDACTADA]'),
            # URLs con credenciales embebidas (user:pass@host)
            (r'https?://[^:\s]+:[^@\s]+@[^\s/]+', '[URL-PROTEGIDA]')
        ]
        
        resultado = texto
        for patron, remplazo in patrones:
            resultado = re.sub(patron, remplazo, resultado)
        return resultado

    def _start_timer(self):
        """Inicia un temporizador para flush por tiempo."""
        self.timer = threading.Timer(self.flush_timeout, self._timer_callback)
        self.timer.daemon = True
        self.timer.start()

    def _timer_callback(self):
        if self.pending_changes > 0:
            logger.debug("Flush por timeout (30s)")
            self.flush()
        self._start_timer()

    def flush(self):
        """Escribe el historial al disco inmediatamente."""
        with self.lock:
            if self.pending_changes == 0:
                return
                
            try:
                temp = self.archivo.with_suffix(".tmp")
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(self.historial, f, ensure_ascii=False, indent=2)
                temp.replace(self.archivo)
                self.pending_changes = 0
                self.last_flush_time = time.time()
                logger.debug("Historial persistido correctamente.")
            except Exception as e:
                logger.error(f"Error en flush de historial: {e}")

    def guardar(self, rol: str, texto: str):
        """Guarda un nuevo mensaje en el buffer con filtrado de seguridad."""
        texto_seguro = self._redactar_sensible(texto)
        texto_final = f"[Largo omitido: {texto_seguro[:50]}...]" if len(texto_seguro) > 1000 else texto_seguro
        
        with self.lock:
            self.historial.append({"role": "user" if rol == "user" else "model", "text": texto_final})
            
            if len(self.historial) > self.max_items:
                self.historial = self.historial[-self.max_items:]
            
            self.pending_changes += 1

        # Decidir si hacer flush inmediato por tamaño de buffer
        if self.pending_changes >= self.buffer_size:
            self.flush()
